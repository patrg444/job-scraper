import time
import random
import re # Added for _norm
import os
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.support.ui import Select
# For type hinting WebElement
from selenium.webdriver.remote.webelement import WebElement

logger = logging.getLogger(__name__)

class FormHandler:
    def __init__(self, driver, wait, short_wait, easy_apply_bot_instance):
        self.driver = driver
        self.wait = wait
        self.short_wait = short_wait
        self.bot = easy_apply_bot_instance # Reference to the main bot instance

    def _get_raw_text(self, el: WebElement) -> str:
        # Tactic #1: Switch from element.text / innerText → textContent
        try:
            return self.driver.execute_script("return arguments[0].textContent;", el) or ""
        except Exception as e:
            logger.debug(f"Error in _get_raw_text: {e}")
            return ""

    def _norm(self, t: str) -> str:
        # Tactic #2: Normalise once, early
        return re.sub(r'\s+', ' ', t or '').strip().lower()

    def _semantic_label(self, field_el: WebElement) -> str:
        # Tactic #3: Four-way “semantic label” lookup
        # 1. <label for="id">
        try:
            fid = field_el.get_attribute('id')
            if fid:
                # Use find_elements to avoid NoSuchElementException if not found
                lbl_elements = self.driver.find_elements(By.CSS_SELECTOR, f"label[for='{fid}']")
                if lbl_elements and lbl_elements[0].is_displayed():
                    raw_text = self._get_raw_text(lbl_elements[0])
                    if raw_text.strip():
                        return self._norm(raw_text)
        except StaleElementReferenceException:
            logger.debug("StaleElementReferenceException in _semantic_label (label for id)")
        except Exception as e:
            logger.debug(f"Error in _semantic_label (label for id): {e}")

        # 2. aria-labelledby chain
        try:
            aria_labelledby = field_el.get_attribute('aria-labelledby')
            if aria_labelledby:
                bits = []
                for ref_id in aria_labelledby.split():
                    try:
                        # It's safer to find the element first, then get its textContent
                        ref_el = self.driver.find_element(By.ID, ref_id)
                        txt = self._get_raw_text(ref_el)
                        if txt.strip():
                            bits.append(self._norm(txt))
                    except NoSuchElementException:
                        logger.debug(f"Could not find element with ID '{ref_id}' for aria-labelledby.")
                        continue # Skip this ref_id if not found
                if bits:
                    return self._norm(" ".join(bits))
        except StaleElementReferenceException:
            logger.debug("StaleElementReferenceException in _semantic_label (aria-labelledby)")
        except Exception as e:
            logger.debug(f"Error in _semantic_label (aria-labelledby): {e}")


        # 3. aria-label / placeholder / title
        for attr in ('aria-label', 'placeholder', 'title'):
            try:
                txt = field_el.get_attribute(attr)
                if txt and txt.strip():
                    return self._norm(txt)
            except StaleElementReferenceException:
                logger.debug(f"StaleElementReferenceException in _semantic_label ({attr})")
                # If one attribute is stale, others might still be valid, so continue
            except Exception as e:
                logger.debug(f"Error in _semantic_label ({attr}): {e}")
        
        # 4. nearest preceding <span>/<p>
        # This is a bit fragile and should be a last resort.
        # It's also slow due to XPath.
        try:
            # Using find_elements to avoid exception if not found
            sib_elements = field_el.find_elements(
                By.XPATH,
                "preceding-sibling::*[(self::span or self::p or self::legend or self::label) and normalize-space()!=''][1]"
            )
            if sib_elements and sib_elements[0].is_displayed():
                raw_text = self._get_raw_text(sib_elements[0])
                if raw_text.strip():
                    return self._norm(raw_text)
        except StaleElementReferenceException:
            logger.debug("StaleElementReferenceException in _semantic_label (preceding-sibling)")
        except Exception as e:
            logger.debug(f"Error in _semantic_label (preceding-sibling): {e}")

        # Fallback to name attribute if nothing else is found
        try:
            name_attr = field_el.get_attribute("name")
            if name_attr and name_attr.strip():
                return self._norm(name_attr.replace("_", " ").title())
        except: pass # Ignore errors for this last fallback

        return self._norm(f"Unknown Field (ID: {field_el.get_attribute('id')}, Name: {field_el.get_attribute('name')})")


    def _get_form_elements_on_page(self):
        logger.info("Scanning page for form elements (FormHandler)...")
        form_items = []
        processed_element_ids = set()
        form_container = None
        form_container_selector_used = "N/A"
        form_container_selectors = [
            "div.jobs-easy-apply-modal__content", # Primary Easy Apply modal
            "div.artdeco-modal__content",         # Generic Artdeco modal content
            "form[data-test-form='true']"         # Specific data-test attribute
        ]
        for sel_container in form_container_selectors:
            try:
                form_container_candidate = self.driver.find_element(By.CSS_SELECTOR, sel_container)
                if form_container_candidate.is_displayed(): # Tactic #5 applied here for container
                    form_container = form_container_candidate
                    form_container_selector_used = sel_container 
                    logger.info(f"Found and using displayed form container with selector: {sel_container}")
                    break 
                else: 
                    logger.debug(f"Form container found with {sel_container} but it was not displayed.")
            except NoSuchElementException:
                logger.debug(f"Form container not found with selector: {sel_container}")
                pass 
        
        if form_container is None: 
            logger.warning("Specific form containers not found or not displayed, falling back to searching entire page for form elements.")
            form_container = self.driver # Fallback to entire driver scope
            form_container_selector_used = "self.driver (full page)"
        else:
            logger.info(f"Final form_container for element search is based on selector: {form_container_selector_used}")

        # Education section detection (remains largely the same, uses .text which is fine for headers)
        education_section_header_selectors = [
            (By.XPATH, ".//h2[normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))='education']"), 
            (By.XPATH, ".//h3[normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))='education']"),
            (By.XPATH, ".//legend[normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))='education']"),
            (By.XPATH, ".//*[(@role='heading' or contains(@class, 'form-sub-section-title') or contains(@class, 'section-header') or contains(@class, 'fb-form-element-label')) and (contains(normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')), 'education') or contains(normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')), 'school'))]"),
        ]
        education_section_found = False
        for by, sel_edu_head in education_section_header_selectors: 
            try:
                headers = form_container.find_elements(by, sel_edu_head) 
                for header_el in headers:
                    if header_el.is_displayed(): # Tactic #5
                        text_content = self._norm(self._get_raw_text(header_el)) # Use norm for comparison
                        if "education" in text_content or "school" in text_content or "university" in text_content:
                            logger.info(f"Detected 'Education' section trigger: {self._get_raw_text(header_el).strip()}")
                            form_items.append({'type': 'education_section', 'element': header_el}) 
                            education_section_found = True; break
                if education_section_found: break
            except: continue
        
        try:
            # NEW: Broaden search for file inputs to the whole modal, not just form_container
            try:
                modal_element = self.driver.find_element(By.CSS_SELECTOR, "div.jobs-easy-apply-modal")
                # Grab all file inputs within the modal, regardless of style or disabled state initially
                upload_inputs = modal_element.find_elements(By.CSS_SELECTOR, "input[type='file']")
                logger.info(f"Found {len(upload_inputs)} input[type='file'] elements within the entire modal.")
            except NoSuchElementException:
                logger.warning("Could not find the main 'div.jobs-easy-apply-modal'. Falling back to form_container for file inputs.")
                # Fallback to original form_container if the main modal isn't found (should be rare)
                upload_inputs = form_container.find_elements(By.CSS_SELECTOR, "input[type='file']") # Simpler selector for fallback
                logger.info(f"Fallback: Found {len(upload_inputs)} input[type='file'] elements within form_container.")

            for up_input in upload_inputs:
                # Tactic #5: Skip invisible / template nodes - MODIFIED:
                # We will make them visible before send_keys if needed.
                # The primary check here is if it's a known interactable hidden pattern or genuinely part of the form.
                
                input_id = up_input.get_attribute('id') or ""
                # Check if it's the specific known hidden upload pattern OR if it's actually displayed.
                # This allows us to include the `style="display:none"` ones if they match the known ID pattern.
                is_known_hidden_upload_pattern = "jobs-document-upload-file-input" in input_id
                
                # If it's not displayed AND it's not our known hidden pattern, then skip.
                if not up_input.is_displayed() and not is_known_hidden_upload_pattern:
                    logger.debug(f"Skipping file input (ID: {input_id}) because it's not displayed and not the known hidden upload pattern.")
                    continue

                # If it's already processed, skip.
                if input_id and input_id in processed_element_ids:
                    logger.debug(f"Skipping already processed file input (ID: {input_id}).")
                    continue
                
                # At this point, the input is either displayed, or it's the known hidden one we want to interact with.
                # Also, ensure it's not disabled before attempting to process, even if hidden.
                if up_input.get_attribute('disabled') is not None:
                    logger.debug(f"Skipping file input (ID: {input_id}) because it is disabled.")
                    continue

                label_for_upload = self._semantic_label(up_input) # Use new label function
                item_label = 'Unknown File Upload'
                if "resume" in label_for_upload or "cv" in label_for_upload or "jobs-document-upload-file-input-upload-resume" in input_id:
                    item_label = 'Resume Upload'
                elif "cover letter" in label_for_upload or "jobs-document-upload-file-input-upload-cover-letter" in input_id:
                    item_label = 'Cover Letter Upload'
                
                form_items.append({'type': 'file_input', 'element': up_input, 'label': item_label}) # Store normalized label
                if input_id: processed_element_ids.add(input_id)
        except Exception as e: logger.debug(f"Error finding file inputs: {e}")

        form_element_configs = {
            'text_input': [
                (By.CSS_SELECTOR, "input[type='text']"), (By.CSS_SELECTOR, "input[type='tel']"),
                (By.CSS_SELECTOR, "input[type='email']"), (By.CSS_SELECTOR, "textarea")
            ],
            'checkbox': [
                (By.CSS_SELECTOR, "input[type='checkbox']"), (By.XPATH, ".//*[@role='checkbox']")
            ]
        }
        for el_type, find_methods in form_element_configs.items():
            for by_method, selector_item in find_methods: 
                try:
                    elements = form_container.find_elements(by_method, selector_item)
                    for el in elements:
                        # Tactic #5: Skip invisible / template nodes
                        if not el.is_displayed() or (el.rect['height'] == 0 and el.rect['width'] == 0) :
                            logger.debug(f"Skipping non-displayed {el_type} (Selector: {selector_item}, ID: {el.get_attribute('id')}) per Tactic #5.")
                            continue

                        el_id = el.get_attribute('id')
                        if (not el_id or el_id not in processed_element_ids):
                            if el_type in ['checkbox', 'radio'] and by_method == By.XPATH: # Existing logic for role-based
                                try:
                                    parent_label = el.find_element(By.XPATH, "./ancestor::label[1]")
                                    if parent_label.get_attribute("for"): 
                                        if parent_label.get_attribute("for") in processed_element_ids:
                                            logger.debug(f"Skipping role-based {el_type} '{el_id}' as it seems part of a label for an already processed input.")
                                            continue
                                except NoSuchElementException: pass 

                            label = self._semantic_label(el) # Use new label function
                            form_items.append({'type': el_type, 'element': el, 'label': label}) # Store normalized label
                            if el_id: processed_element_ids.add(el_id)
                except Exception as e: logger.debug(f"Error finding {selector_item} (method {by_method}) for type {el_type}: {e}")
            
        try:
            elements = form_container.find_elements(By.CSS_SELECTOR, "select")
            for el in elements:
                # Tactic #5
                if not el.is_displayed() or (el.rect['height'] == 0 and el.rect['width'] == 0):
                    logger.debug(f"Skipping non-displayed select (ID: {el.get_attribute('id')}) per Tactic #5.")
                    continue
                el_id = el.get_attribute('id')
                if (not el_id or el_id not in processed_element_ids):
                    if el_id and "globalfooter-select_language" in el_id:
                        logger.debug(f"Skipping global language dropdown: {el_id}")
                        continue
                    label = self._semantic_label(el) # Use new label function
                    form_items.append({'type': 'dropdown', 'element': el, 'label': label}) # Store normalized label
                    if el_id: processed_element_ids.add(el_id)
        except Exception as e: logger.debug(f"Error finding dropdowns: {e}")

        # Radio group handling - needs careful application of new label logic
        try:
            # ... (explicit wait for radio groups, largely unchanged) ...
            radiogroup_elements = form_container.find_elements(By.XPATH, ".//*[@role='radiogroup']")
            if radiogroup_elements:
                logger.info(f"Found {len(radiogroup_elements)} elements with role='radiogroup'.")
                for rg_el in radiogroup_elements:
                    # Tactic #5
                    if not rg_el.is_displayed() or (rg_el.rect['height'] == 0 and rg_el.rect['width'] == 0):
                        logger.debug(f"Skipping non-displayed radiogroup (ID: {rg_el.get_attribute('id')}) per Tactic #5.")
                        continue
                    rg_id = rg_el.get_attribute('id')
                    if (not rg_id or rg_id not in processed_element_ids):
                        group_label = self._semantic_label(rg_el) 
                        options_in_group_elements = rg_el.find_elements(By.XPATH, ".//*[@role='radio']")
                        if not options_in_group_elements: 
                            options_in_group_elements = rg_el.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                        
                        # Filter out non-displayed options within the group
                        visible_options_in_group = [opt for opt in options_in_group_elements if opt.is_displayed()]

                        if visible_options_in_group:
                            group_name_for_dict = rg_id or f"radiogroup_{len(form_items)}"
                            # Extract normalized option texts for fingerprinting (Tactic #4 prep)
                            opt_texts = [self._semantic_label(opt_el) for opt_el in visible_options_in_group]
                            form_items.append({
                                'type': 'radio_group', 
                                'name': group_name_for_dict, 
                                'elements': visible_options_in_group, 
                                'label': group_label, # Already normalized
                                'options_text': opt_texts # Store normalized option texts
                            })
                            if rg_id: processed_element_ids.add(rg_id) 
                            for opt_el in visible_options_in_group: 
                                opt_id = opt_el.get_attribute('id')
                                if opt_id: processed_element_ids.add(opt_id)
            
            radio_groups_by_name = {}
            all_input_radios = form_container.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            logger.info(f"Found {len(all_input_radios)} raw input[type='radio'] elements initially (FormHandler).")
            # ... (debug logging for no radios, largely unchanged) ...
            
            for idx, radio_el in enumerate(all_input_radios):
                # Tactic #5
                try:
                    is_displayed_status = radio_el.is_displayed()
                    if not is_displayed_status or (radio_el.rect['height'] == 0 and radio_el.rect['width'] == 0):
                        logger.debug(f"Skipping non-displayed raw radio {idx} (ID: {radio_el.get_attribute('id')}) per Tactic #5.")
                        continue
                except StaleElementReferenceException:
                    logger.warning(f"Radio el {idx} became stale before visibility/rect check. Skipping.")
                    continue
                
                el_id = radio_el.get_attribute('id')
                el_name = radio_el.get_attribute("name")
                # ... (rest of existing raw radio processing logic, largely unchanged, but ensure labels are handled by _semantic_label later) ...
                if (not el_id or el_id not in processed_element_ids): 
                    if not el_name: 
                        logger.debug(f"Radio input {el_id} (Value: {radio_el.get_attribute('value')}) has no name, cannot group by name. Skipping.")
                        continue 
                    if el_name not in radio_groups_by_name:
                        radio_groups_by_name[el_name] = {'elements': [], 'label': None, 'options_text': []}
                    radio_groups_by_name[el_name]['elements'].append(radio_el)
                # ... (logging for skipped radios) ...

            logger.info(f"Formed {len(radio_groups_by_name)} radio groups by name (FormHandler).")
            for name, group_data in radio_groups_by_name.items():
                if group_data['elements']:
                    # Ensure all elements in the group are visible before processing
                    visible_elements_in_group = [el for el in group_data['elements'] if el.is_displayed()]
                    if not visible_elements_in_group:
                        logger.debug(f"Skipping radio group '{name}' as all its elements are non-displayed.")
                        continue
                    
                    first_radio_in_group = visible_elements_in_group[0]
                    group_label = self._semantic_label(first_radio_in_group) # Get group label from first element
                    
                    # Attempt to find a better group label (e.g., from fieldset legend or preceding title)
                    # This logic can be refined or integrated into _semantic_label if a common pattern exists
                    try:
                        fieldset_ancestor = first_radio_in_group.find_element(By.XPATH, "./ancestor::fieldset[1]")
                        legend_text = self._semantic_label(fieldset_ancestor) # _semantic_label can try legend
                        if legend_text and not legend_text.startswith("unknown field"):
                            group_label = legend_text
                        else: # Try preceding span if legend didn't work well
                            wlua_container_div = fieldset_ancestor.find_element(By.XPATH, "./ancestor::div[contains(@class, 'WLuaJhvgErSbaETfXglkhUoEmiKpEvBxEYdaXevE')][1]")
                            potential_title_span = wlua_container_div.find_element(By.XPATH, "./preceding-sibling::span[contains(@class, 'jobs-easy-apply-form-section__group-title')][1]")
                            if potential_title_span and potential_title_span.is_displayed():
                                better_label_text = self._norm(self._get_raw_text(potential_title_span))
                                if better_label_text and len(better_label_text.split()) >= 2: # Allow shorter if it's a good title
                                    group_label = better_label_text
                    except Exception: pass # If finding better label fails, stick with the one from first radio

                    # Extract normalized option texts for fingerprinting (Tactic #4 prep)
                    opt_texts = [self._semantic_label(opt_el) for opt_el in visible_elements_in_group]

                    form_items.append({
                        'type': 'radio_group', 
                        'name': name, 
                        'elements': visible_elements_in_group, 
                        'label': group_label, # Already normalized
                        'options_text': opt_texts # Store normalized option texts
                    })
                    for radio_el in visible_elements_in_group: 
                         if radio_el.get_attribute('id'): processed_element_ids.add(radio_el.get_attribute('id'))
        except Exception as e: logger.debug(f"Error finding radio groups (FormHandler): {e}")

        logger.info(f"Page scan (FormHandler) found {len(form_items)} interactable items/sections.")
        return form_items

    def _handle_form_fields(self, current_step_number, job_url_for_debug="", max_steps_for_debug=15):
        try:
            form_items_to_process = self._get_form_elements_on_page()
            # ... (rest of the method, ensuring item.get('label') is used where appropriate, which is now normalized) ...
            if not form_items_to_process:
                logger.info("No form items detected by scanner on this page (FormHandler).")
                # ... (debug save logic) ...
                return

            for item in form_items_to_process:
                item_type = item['type']
                element = item.get('element') 
                label_from_scan = item.get('label') # This label is already normalized by _semantic_label

                if item_type == 'education_section':
                    self._handle_education_entries() 
                elif item_type == 'experience_section': 
                    self._handle_experience_entries()
                elif item_type == 'file_input' and element:
                    self._handle_single_file_input(element, label_from_scan) # Pass normalized label
                elif item_type == 'text_input' and element:
                    self._fill_single_text_input(element, label_from_scan)
                elif item_type == 'dropdown' and element:
                    self._fill_single_dropdown(element, label_from_scan, item.get('options_text', []))
                elif item_type == 'radio_group': 
                    self._fill_single_radio_group(item.get('name'), item.get('elements'), label_from_scan, item.get('options_text', []))
                elif item_type == 'checkbox' and element:
                    self._fill_single_checkbox(element, label_from_scan)
                
                time.sleep(random.uniform(0.1, 0.3)) 
        except Exception as e: 
            logger.error(f"Error in _handle_form_fields (FormHandler): {e}", exc_info=True)

    def _handle_single_file_input(self, upload_input_element, label_text_normalized): # Accept normalized label
        try:
            input_id = upload_input_element.get_attribute('id') or ""
            logger.debug(f"Handling file input: '{label_text_normalized}' (ID: {input_id})")

            # Safer 'already-uploaded' check
            try:
                # Search within the broader modal for the confirmation chip
                modal_el_for_check = self.driver.find_element(By.CSS_SELECTOR, "div.jobs-easy-apply-modal")
                if "resume" in label_text_normalized or "cv" in label_text_normalized:
                    # Check for the visual confirmation of an already uploaded resume
                    uploaded_resume_titles = modal_el_for_check.find_elements(By.CSS_SELECTOR, "span.jobs-document-upload-entity__title")
                    if uploaded_resume_titles and uploaded_resume_titles[0].is_displayed() and uploaded_resume_titles[0].text.strip():
                        logger.info(f"Resume '{uploaded_resume_titles[0].text}' already appears selected/uploaded for '{label_text_normalized}'. Skipping upload.")
                        return
            except Exception as e_check_uploaded:
                logger.debug(f"Could not perform 'already-uploaded' check for '{label_text_normalized}', or no file visibly uploaded yet: {e_check_uploaded}")

            file_to_upload = None
            if "resume" in label_text_normalized or "cv" in label_text_normalized:
                file_to_upload = self.bot.resume_path 
            elif "cover letter" in label_text_normalized:
                file_to_upload = self.bot.form_answers.get("cover_letter_path", "") 
            
            if file_to_upload and os.path.exists(file_to_upload):
                logger.info(f"Attempting to upload '{file_to_upload}' to file input for '{label_text_normalized}' (ID: {input_id})")
                try:
                    # Make the element programmatically interactable by removing disabled and style attributes
                    logger.info(f"Preparing file input '{label_text_normalized}' (ID: {input_id}) by removing 'disabled' and 'style' attributes.")
                    # Using triple-quoted string for robust multi-line JavaScript
                    js_script = """
                        arguments[0].removeAttribute('disabled');
                        arguments[0].removeAttribute('style');
                        arguments[0].style.display='block';
                        arguments[0].style.visibility='visible';
                        arguments[0].style.height='1px';
                        arguments[0].style.width='1px';
                        arguments[0].style.opacity='1';
                        arguments[0].style.position='fixed';
                        arguments[0].style.top='0px';
                        arguments[0].style.left='0px';
                        arguments[0].style.zIndex='2147483647';
                    """
                    self.driver.execute_script(js_script, upload_input_element)
                    time.sleep(0.5) # Pause for JS to apply and DOM to update

                    upload_input_element.send_keys(file_to_upload)
                    logger.info(f"Sent keys '{os.path.basename(file_to_upload)}' to file input '{label_text_normalized}'.")
                    
                    # Confirm the upload before clicking “Next”
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "span.jobs-document-upload-entity__title"))
                    )
                    logger.info(f"✅ Resume appears uploaded for '{label_text_normalized}'.")
                    time.sleep(random.uniform(0.5, 1.0)) # Brief pause after confirmation
                
                except Exception as e_send_keys:
                    logger.error(f"Upload process failed for file input '{label_text_normalized}' (ID: {input_id}): {e_send_keys}. Skipping.", exc_info=True)
            elif file_to_upload: 
                logger.warning(f"File path '{file_to_upload}' for '{label_text_normalized}' (ID: {input_id}) does not exist. Skipping upload.")
            else:
                logger.info(f"No file to upload for '{label_text_normalized}' (ID: {input_id}).")
        # This was the 'try' statement that Pylance reported as missing an except/finally (Line 433 in previous error)
        # It's the outer try for the whole _handle_single_file_input method.
        except Exception as e: 
            logger.error(f"Outer file upload error (FormHandler) for element (ID: {upload_input_element.get_attribute('id') if upload_input_element else 'N/A'}): {e}", exc_info=True)

    def _fill_single_text_input(self, input_field, label_text_normalized): # label_text is already normalized
        try:
            # Visibility/enabled check already done in _get_form_elements_on_page
            answer = None
            # label_text_normalized is already lowercased
            if 'email' in label_text_normalized: answer = self.bot.email 
            elif any(kw in label_text_normalized for kw in ['phone', 'mobile number', 'telephone']): answer = self.bot.resume_data.get("phone")
            elif any(kw in label_text_normalized for kw in ['first name', 'firstname', 'given name']): answer = self.bot.resume_data.get("first_name")
            elif any(kw in label_text_normalized for kw in ['last name', 'lastname', 'surname', 'family name']): answer = self.bot.resume_data.get("last_name")
            else: answer = self.bot._get_answer_for_question(label_text_normalized, is_dropdown=False) # Pass normalized label
            
            current_value = self._norm(input_field.get_attribute('value') or "")
            if answer is not None and self._norm(str(answer)) == current_value and current_value: # Compare normalized
                logger.info(f"Field '{label_text_normalized}' already correctly filled with '{current_value}'. Skipping.")
                return

            if answer and self._norm(str(answer)) != "n/a" and not (isinstance(answer, str) and answer.startswith("LLM_CANDIDATE_")):
                input_field.clear()
                self.bot._type_slowly(input_field, str(answer)) 
                logger.info(f"Filled '{str(answer)}' into text input '{label_text_normalized}'.")
            # ... (rest of logic unchanged) ...
        except Exception as e: 
            logger.error(f"Error handling text input (FormHandler) '{label_text_normalized}': {e}")

    def _fill_single_dropdown(self, dropdown_el, label_text_normalized, option_texts_normalized=None): # label_text is normalized
        try:
            # Visibility/enabled check done in _get_form_elements_on_page
            answer_to_select_raw = self.bot._get_answer_for_question(label_text_normalized, is_dropdown=True) # Pass normalized label
            if not answer_to_select_raw or str(answer_to_select_raw).strip().upper() in ["N/A", ""] or str(answer_to_select_raw).startswith("LLM_CANDIDATE_"):
                logger.info(f"No specific answer or 'N/A' for dropdown '{label_text_normalized}'. Skipping.")
                return

            answer_to_select_normalized = self._norm(str(answer_to_select_raw))
            select_obj = Select(dropdown_el)
            
            try:
                current_selection_text_normalized = self._norm(select_obj.first_selected_option.text)
                if current_selection_text_normalized == answer_to_select_normalized:
                    logger.info(f"Dropdown '{label_text_normalized}' already correctly selected with '{answer_to_select_raw}'. Skipping.")
                    return
            except Exception: pass # Ignore if no option is selected or error getting it

            selected_successfully = False
            available_options_normalized = [(self._norm(opt.text), opt.text) for opt in select_obj.options]

            for norm_opt_text, orig_opt_text in available_options_normalized:
                if norm_opt_text == answer_to_select_normalized:
                    select_obj.select_by_visible_text(orig_opt_text)
                    logger.info(f"Selected '{orig_opt_text}' for '{label_text_normalized}' by exact normalized text match.")
                    selected_successfully = True; break
            if selected_successfully: return

            for norm_opt_text, orig_opt_text in available_options_normalized:
                if answer_to_select_normalized in norm_opt_text or norm_opt_text in answer_to_select_normalized:
                    select_obj.select_by_visible_text(orig_opt_text)
                    logger.info(f"Selected '{orig_opt_text}' for '{label_text_normalized}' by partial normalized text match ('{answer_to_select_raw}').")
                    selected_successfully = True; break
            if selected_successfully: return
            
            # Fallback to value attribute if text match fails
            for option_element in select_obj.options:
                option_value = option_element.get_attribute('value')
                if option_value and self._norm(option_value) == answer_to_select_normalized:
                    select_obj.select_by_value(option_value)
                    logger.info(f"Selected option with value '{option_value}' for '{label_text_normalized}' matching answer '{answer_to_select_raw}'.")
                    selected_successfully = True; break
            if selected_successfully: return

            if not selected_successfully:
                logger.warning(f"Could not find option matching '{answer_to_select_raw}' (normalized: '{answer_to_select_normalized}') for dropdown '{label_text_normalized}'. Options (first 5 normalized): {[o[0] for o in available_options_normalized[:5]]}...")
        except Exception as e_dropdown:
            logger.error(f"Error handling dropdown (FormHandler) '{label_text_normalized}': {e_dropdown}", exc_info=True)

    def _fill_single_radio_group(self, group_name, radio_buttons_in_group, group_label_text_normalized, option_texts_normalized=None): # group_label_text is normalized
        try:
            answer_to_select_raw = self.bot._get_answer_for_question(group_label_text_normalized, is_dropdown=False) # Pass normalized label
            if not answer_to_select_raw or str(answer_to_select_raw).strip().upper() in ["N/A", ""] or str(answer_to_select_raw).startswith("LLM_CANDIDATE_"):
                logger.info(f"No specific answer or 'N/A' for radio group '{group_label_text_normalized}'. Skipping.")
                return

            answer_to_select_normalized = self._norm(str(answer_to_select_raw))
            selected_an_option = False

            for radio_button in radio_buttons_in_group: # These are already filtered for visibility
                # Get normalized label for this specific radio option
                option_label_text_normalized = self._semantic_label(radio_button) 
                option_value_normalized = self._norm(radio_button.get_attribute('value') or "")
                
                match_found = False
                if option_label_text_normalized == answer_to_select_normalized: match_found = True
                elif option_value_normalized and option_value_normalized == answer_to_select_normalized: match_found = True
                # Partial matches can be risky with normalized text, prefer exact or value match
                # elif answer_to_select_normalized in option_label_text_normalized and option_label_text_normalized: match_found = True
                # elif option_value_normalized and answer_to_select_normalized in option_value_normalized: match_found = True

                if match_found:
                    if radio_button.is_selected():
                        logger.info(f"Radio option '{option_label_text_normalized or option_value_normalized}' already selected for '{group_label_text_normalized}'.")
                        selected_an_option = True; break
                    if self.bot._click_element_robustly(radio_button, f"radio option '{option_label_text_normalized or option_value_normalized}'"):
                        logger.info(f"Selected radio option '{option_label_text_normalized or option_value_normalized}' for question '{group_label_text_normalized}'.")
                        selected_an_option = True
                    else:
                        logger.warning(f"Failed to click radio option '{option_label_text_normalized or option_value_normalized}' for '{group_label_text_normalized}'.")
                    break 
            if not selected_an_option:
                logger.warning(f"Could not find or select radio option matching '{answer_to_select_raw}' (normalized: '{answer_to_select_normalized}') for group '{group_label_text_normalized}'.")
        except Exception as e:
            logger.error(f"Error in _fill_single_radio_group (FormHandler) for '{group_label_text_normalized}': {e}", exc_info=True)

    def _fill_single_checkbox(self, checkbox_element, label_text_normalized): # label_text is normalized
        try:
            # Visibility/enabled check done in _get_form_elements_on_page
            answer_str_raw = self.bot._get_answer_for_question(label_text_normalized, is_dropdown=False) # Pass normalized label
            should_be_checked = None
            if isinstance(answer_str_raw, bool): should_be_checked = answer_str_raw
            elif isinstance(answer_str_raw, str):
                answer_lower_normalized = self._norm(answer_str_raw) # Normalize answer from config too
                if answer_lower_normalized in ["yes", "true", "checked", "selected"]: should_be_checked = True
                elif answer_lower_normalized in ["no", "false", "unchecked", "unselected", "n/a"]: should_be_checked = False
            
            if should_be_checked is None:
                logger.warning(f"Could not determine desired state for checkbox '{label_text_normalized}' from answer '{answer_str_raw}'. Skipping.")
                return
            
            is_currently_checked = checkbox_element.is_selected()
            if should_be_checked and not is_currently_checked:
                logger.info(f"Checkbox '{label_text_normalized}' should be checked. Clicking.")
                self.bot._click_element_robustly(checkbox_element, f"checkbox '{label_text_normalized}'")
            elif not should_be_checked and is_currently_checked:
                logger.info(f"Checkbox '{label_text_normalized}' should be unchecked. Clicking.")
                self.bot._click_element_robustly(checkbox_element, f"checkbox '{label_text_normalized}'")
            else:
                logger.info(f"Checkbox '{label_text_normalized}' is already in the desired state (Checked: {is_currently_checked}).")
        except Exception as e:
            logger.error(f"Error handling checkbox (FormHandler) '{label_text_normalized}': {e}", exc_info=True)
    
    # _handle_date_fields, _handle_education_entries, _handle_experience_entries remain largely the same,
    # but internal calls to _get_field_label should be updated to _semantic_label.
    # For brevity, I'll show the change in _handle_date_fields as an example.

    def _handle_date_fields(self, parent_form_element, date_field_group_label, date_str_yyyy_mm): # date_field_group_label is passed from resume, not from page scan
        logger.info(f"Attempting to handle date field (FormHandler) '{date_field_group_label}' for date '{date_str_yyyy_mm}'")
        if not date_str_yyyy_mm or '-' not in date_str_yyyy_mm:
            logger.warning(f"Invalid date string format for {date_field_group_label}: {date_str_yyyy_mm}. Expected YYYY-MM.")
            return False
        try:
            year_str, month_str = date_str_yyyy_mm.split('-')
            month_int = int(month_str) 
        except ValueError:
            logger.warning(f"Could not parse year/month from {date_str_yyyy_mm} for {date_field_group_label}.")
            return False
        month_names = ["January", "February", "March", "April", "May", "June", 
                       "July", "August", "September", "October", "November", "December"]
        target_month_name_normalized = self._norm(month_names[month_int - 1]) # Normalize target month name
        
        year_dropdown_found = False
        try:
            year_selects = parent_form_element.find_elements(By.TAG_NAME, "select")
            for ys in year_selects:
                if not ys.is_displayed(): continue
                ys_label_normalized = self._semantic_label(ys) # Use new label function
                if "year" in ys_label_normalized or self._norm(date_field_group_label + " year") in ys_label_normalized :
                    select_obj = Select(ys)
                    select_obj.select_by_visible_text(year_str) 
                    logger.info(f"Selected year '{year_str}' for '{date_field_group_label}'.")
                    year_dropdown_found = True; break
            if not year_dropdown_found:
                 logger.warning(f"Could not find or select year dropdown for '{date_field_group_label}'.")
                 return False
        except Exception as e:
            logger.error(f"Error selecting year for {date_field_group_label}: {e}")
            return False
        
        month_dropdown_found = False
        try:
            month_selects = parent_form_element.find_elements(By.TAG_NAME, "select")
            for ms in month_selects:
                if not ms.is_displayed(): continue
                ms_label_normalized = self._semantic_label(ms) # Use new label function
                if "month" in ms_label_normalized or self._norm(date_field_group_label + " month") in ms_label_normalized:
                    select_obj = Select(ms)
                    for option in select_obj.options:
                        if self._norm(option.text) == target_month_name_normalized:
                            select_obj.select_by_visible_text(option.text)
                            logger.info(f"Selected month '{option.text}' for '{date_field_group_label}'.")
                            month_dropdown_found = True; break
                    if month_dropdown_found: break
                    # Fallback to value if text match fails
                    try: 
                        select_obj.select_by_value(month_str) 
                        logger.info(f"Selected month by value '{month_str}' for '{date_field_group_label}'.")
                        month_dropdown_found = True; break
                    except NoSuchElementException:
                        try:
                            select_obj.select_by_value(str(month_int)) 
                            logger.info(f"Selected month by value '{str(month_int)}' for '{date_field_group_label}'.")
                            month_dropdown_found = True; break
                        except NoSuchElementException:
                            logger.warning(f"Could not select month '{target_month_name_normalized}' (or value '{month_str}') for '{date_field_group_label}'.")
            if not month_dropdown_found:
                logger.warning(f"Could not find or select month dropdown for '{date_field_group_label}'.")
                return False
        except Exception as e:
            logger.error(f"Error selecting month for {date_field_group_label}: {e}")
            return False
        return True

    # _handle_education_entries and _handle_experience_entries would also need _semantic_label
    # For brevity, these are omitted but the pattern of replacing _get_field_label with _semantic_label applies.
    def _handle_education_entries(self):
        logger.info("Attempting to handle education entries (FormHandler)...")
        # ... (existing logic, ensure any _get_field_label calls are replaced with _semantic_label) ...
        # Example change within a helper if it existed or inline:
        # current_el_label = self._semantic_label(el)
        pass

    def _handle_experience_entries(self): 
        logger.info("Placeholder for _handle_experience_entries (FormHandler)")
        pass

    def _extract_fields_for_question_collection(self): # This method is for question collection, not application filling
        fields_info = []
        # Simplified label getter for collection, as it's less critical than application filling
        def get_label_info_for_collection(element):
            # Using _semantic_label for consistency, though a simpler one could be used for pure collection
            label_text = self._semantic_label(element)
            has_asterisk = False # Basic asterisk check, can be refined
            try:
                # Check common parent elements for asterisk if not in label itself
                parent_div = element.find_element(By.XPATH, "./ancestor::div[contains(@class, 'fb-form-element') or contains(@class, 'artdeco-form-item')][1]")
                if "*" in self._get_raw_text(parent_div): has_asterisk = True
            except: pass
            if "*" in label_text: has_asterisk = True
            return label_text, has_asterisk
        
        def is_element_required_for_collection(element, label_has_asterisk): 
            if label_has_asterisk: return True
            try: return element.get_attribute("required") is not None or element.get_attribute("aria-required") == "true"
            except: return False

        # Iterate over common form elements
        for el_type, selector in [
            ("textarea", "textarea"), 
            ("text", "input[type='text'], input[type='email'], input[type='tel'], input[type='number'], input:not([type])"), # Added input:not([type]) for default text inputs
            ("dropdown", "select")
            # Checkboxes and radios are handled separately below to group radios by name
        ]:
            elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                if not el.is_displayed() or (el.rect['height'] == 0 and el.rect['width'] == 0) : continue # Tactic #5
                
                label, has_asterisk = get_label_info_for_collection(el)
                required = is_element_required_for_collection(el, has_asterisk)
                options_list = []
                field_type_for_fp = el_type # For fingerprinting

                if el_type == "dropdown":
                    try:
                        select_obj = Select(el)
                        options_list = [self._norm(o.text) for o in select_obj.options if o.text.strip()]
                    except Exception as e: 
                        logger.debug(f"Error extracting options for dropdown {label}: {e}")
                        options_list = ["Error extracting options"]
                
                fields_info.append({
                    "label": label, # Already normalized
                    "type": field_type_for_fp, 
                    "options_text": sorted(list(set(options_list))), # Tactic #4 - sorted, normalized options
                    "is_required": required,
                    "html_element_details": f"tag:{el.tag_name},id:{el.get_attribute('id')},name:{el.get_attribute('name')}"
                })

        # Handle checkboxes
        checkbox_elements = self.driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for el in checkbox_elements:
            if not el.is_displayed() or (el.rect['height'] == 0 and el.rect['width'] == 0) : continue # Tactic #5
            label, has_asterisk = get_label_info_for_collection(el)
            required = is_element_required_for_collection(el, has_asterisk)
            # Checkboxes usually have their label as the main text, and value might be 'on' or specific.
            # For fingerprinting, the label itself is often the "option".
            option_text = label 
            fields_info.append({
                "label": label, 
                "type": "checkbox", 
                "options_text": sorted([option_text]), # Single "option" which is its own label
                "is_required": required,
                "html_element_details": f"tag:{el.tag_name},id:{el.get_attribute('id')},name:{el.get_attribute('name')}"
            })
        
        # Handle radio buttons, grouped by name
        radio_groups = {}
        all_radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        for radio_el in all_radios:
            if not radio_el.is_displayed() or (radio_el.rect['height'] == 0 and radio_el.rect['width'] == 0) : continue # Tactic #5
            name = radio_el.get_attribute("name")
            if not name: 
                # Try to find a group label if name is missing, might be part of a fieldset
                try:
                    fieldset = radio_el.find_element(By.XPATH, "./ancestor::fieldset[1]")
                    name = self._semantic_label(fieldset) # Use fieldset legend as group name
                    if name.startswith("unknown field"): name = f"radiogroup_for_id_{radio_el.get_attribute('id') or random.randint(1000,9999)}"
                except: # Fallback if no fieldset or other grouping found
                    name = f"radiogroup_for_id_{radio_el.get_attribute('id') or random.randint(1000,9999)}"

            if name not in radio_groups:
                radio_groups[name] = {"elements": [], "any_el_req": False, "group_label_candidates": []}
            
            radio_groups[name]["elements"].append(radio_el)
            label_text, has_asterisk = get_label_info_for_collection(radio_el) # Label of individual radio
            # Try to get a group label from fieldset if not already done
            group_label_from_fieldset = ""
            try:
                fieldset = radio_el.find_element(By.XPATH, "./ancestor::fieldset[1]")
                legend_label = self._semantic_label(fieldset)
                if legend_label and not legend_label.startswith("unknown field"):
                    group_label_from_fieldset = legend_label
            except: pass

            if group_label_from_fieldset: radio_groups[name]["group_label_candidates"].append(group_label_from_fieldset)
            if label_text and not label_text.startswith("unknown field"): radio_groups[name]["group_label_candidates"].append(label_text) # Add individual label as candidate if distinct

            if is_element_required_for_collection(radio_el, has_asterisk):
                radio_groups[name]["any_el_req"] = True
        
        for name, grp_data in radio_groups.items():
            # Determine the best group label from candidates
            # Prefer longer, more descriptive labels.
            # This is a simple heuristic; can be improved.
            best_group_label = name # Default to name
            if grp_data["group_label_candidates"]:
                best_group_label = max(set(grp_data["group_label_candidates"]), key=len, default=name)
            
            # Get option texts for this group
            opts_texts_normalized = []
            for r_el in grp_data["elements"]:
                opt_label_text = self._semantic_label(r_el) # Normalized label of the radio option itself
                if opt_label_text and not opt_label_text.startswith("unknown field"):
                    opts_texts_normalized.append(opt_label_text)
                else: # Fallback to value if label is poor
                    opt_val = self._norm(r_el.get_attribute("value") or "")
                    if opt_val: opts_texts_normalized.append(opt_val)
            
            # Ensure all elements in the group share the same requirement status from the first element's perspective
            # This is a simplification; ideally, requirement is per group.
            first_el_in_grp = grp_data["elements"][0]
            _, first_el_has_asterisk = get_label_info_for_collection(first_el_in_grp)
            is_req = grp_data["any_el_req"] or is_element_required_for_collection(first_el_in_grp, first_el_has_asterisk)

            fields_info.append({
                "label": best_group_label, # Already normalized
                "type": "radio_group", 
                "options_text": sorted(list(set(opts_texts_normalized))), # Tactic #4
                "is_required": is_req,
                "html_element_details": f"group_name:{name},num_options:{len(grp_data['elements'])}"
            })
        
        logger.info(f"Extracted {len(fields_info)} fields (FormHandler).")
        return fields_info


    def _handle_validation_errors(self, step_root_element=None):
        """
        Attempts to find and automatically answer unanswered required radio/checkboxes (Pass 1)
        and fix selected-but-invalid radio/checkboxes (Pass 2).
        Uses _semantic_label for better field identification.
        """
        if step_root_element is None:
            try:
                step_root_element = self.driver.find_element(By.CSS_SELECTOR, "div.jobs-easy-apply-modal__content")
            except NoSuchElementException:
                logger.error("Could not find step_root_element for validation error handling.")
                return False

        logger.info("Attempting to handle validation errors by finding unanswered required radio/checkboxes (Pass 1).")
        pass1_fixed_anything = False
        required_radio_groups_fieldsets = step_root_element.find_elements(By.CSS_SELECTOR, "fieldset[aria-required='true']")
        logger.debug(f"Pass 1: Found {len(required_radio_groups_fieldsets)} fieldsets with aria-required='true'.")

        for group_fieldset in required_radio_groups_fieldsets:
            # Tactic #5 for fieldset itself
            if not group_fieldset.is_displayed() or (group_fieldset.rect['height'] == 0 and group_fieldset.rect['width'] == 0):
                logger.debug(f"Skipping non-displayed fieldset for validation (ID: {group_fieldset.get_attribute('id')}).")
                continue
            
            fieldset_label = self._semantic_label(group_fieldset) # Get label for logging
            try:
                # Check if any radio button within this group is already checked AND valid
                checked_radios = group_fieldset.find_elements(By.CSS_SELECTOR, "input[type='radio']:checked")
                if checked_radios and checked_radios[0].is_displayed() and checked_radios[0].get_attribute("aria-invalid") != "true":
                    logger.debug(f"Pass 1: Radio group (label: {fieldset_label}) already has a valid selection. Skipping.")
                    continue

                logger.info(f"Pass 1: Found unanswered or invalidly answered required radio group: {fieldset_label}. Attempting to auto-answer.")
                options_to_try = [
                    ".//label[normalize-space()='No']/preceding-sibling::input[@type='radio' and not(@disabled)]",
                    ".//input[@type='radio' and not(@disabled)][2]", # Second enabled radio
                    ".//input[@type='radio' and not(@disabled)][1]"  # First enabled radio (fallback)
                ]
                target_radio = None
                for xpath_selector in options_to_try:
                    try:
                        potential_targets = group_fieldset.find_elements(By.XPATH, xpath_selector)
                        if potential_targets and potential_targets[0].is_displayed() and potential_targets[0].is_enabled():
                            target_radio = potential_targets[0]
                            logger.info(f"Pass 1: Found target radio option using selector: {xpath_selector} for group {fieldset_label}")
                            break
                    except NoSuchElementException: continue
                
                if target_radio:
                    radio_option_label = self._semantic_label(target_radio)
                    if self.bot._click_element_robustly(target_radio, f"auto-selected radio for group {fieldset_label}, option {radio_option_label}"):
                        logger.info(f"Pass 1: Auto-answered required radio group '{fieldset_label}' with option '{radio_option_label}' (value: '{target_radio.get_attribute('value')}').")
                        pass1_fixed_anything = True; break 
                    else:
                        logger.warning(f"Pass 1: Failed to click auto-selected radio for group '{fieldset_label}'.")
                else:
                    logger.warning(f"Pass 1: Could not find a suitable radio option to auto-select for group '{fieldset_label}'.")
            except Exception as e_radio_group:
                logger.error(f"Pass 1: Error processing a required radio group '{fieldset_label}': {e_radio_group}", exc_info=True)
            if pass1_fixed_anything: return True

        if not pass1_fixed_anything:
            required_checkboxes = step_root_element.find_elements(By.CSS_SELECTOR, "input[type='checkbox'][aria-required='true']")
            logger.debug(f"Pass 1: Found {len(required_checkboxes)} checkboxes with aria-required='true'.")
            for checkbox in required_checkboxes:
                # Tactic #5 for checkbox
                if not checkbox.is_displayed() or (checkbox.rect['height'] == 0 and checkbox.rect['width'] == 0):
                    logger.debug(f"Skipping non-displayed checkbox for validation (ID: {checkbox.get_attribute('id')}).")
                    continue
                
                checkbox_label = self._semantic_label(checkbox)
                try:
                    if not checkbox.is_selected() and checkbox.is_enabled() and checkbox.get_attribute("aria-invalid") != "true":
                        logger.info(f"Pass 1: Found unanswered required checkbox: {checkbox_label}. Attempting to check it.")
                        if self.bot._click_element_robustly(checkbox, f"auto-selected checkbox {checkbox_label}"):
                            logger.info(f"Pass 1: Auto-checked required checkbox '{checkbox_label}'.")
                            pass1_fixed_anything = True; break
                        else:
                            logger.warning(f"Pass 1: Failed to click auto-selected checkbox '{checkbox_label}'.")
                except Exception as e_checkbox:
                    logger.error(f"Pass 1: Error processing a required checkbox '{checkbox_label}': {e_checkbox}", exc_info=True)
                if pass1_fixed_anything: return True
        
        if pass1_fixed_anything: return True

        logger.info("Pass 1 (empty/invalid fields) did not resolve any validation errors or found no such fields. Attempting Pass 2 (swap invalid).")
        
        pass2_fixed_anything = False
        if step_root_element: 
            for bad_input_css_selector in ["input[type='radio'][aria-invalid='true']", "input[type='checkbox'][aria-invalid='true']"]:
                if pass2_fixed_anything: break 
                try:
                    invalid_inputs = step_root_element.find_elements(By.CSS_SELECTOR, bad_input_css_selector)
                    if invalid_inputs:
                        logger.info(f"Pass 2: Found {len(invalid_inputs)} inputs for selector '{bad_input_css_selector}'. Attempting to swap.")
                    
                    for bad_input_element in invalid_inputs:
                        # Tactic #5 for bad_input_element
                        if not bad_input_element.is_displayed() or not bad_input_element.is_enabled() or \
                           (bad_input_element.rect['height'] == 0 and bad_input_element.rect['width'] == 0):
                            logger.debug(f"Skipping non-displayed/disabled invalid input (ID: {bad_input_element.get_attribute('id')}) for Pass 2.")
                            continue
                        
                        bad_input_label = self._semantic_label(bad_input_element)
                        try:
                            # Try to find siblings within the same fieldset or radiogroup
                            parent_group = None
                            try: parent_group = bad_input_element.find_element(By.XPATH, "ancestor::fieldset[1]")
                            except NoSuchElementException:
                                try: parent_group = bad_input_element.find_element(By.XPATH, "ancestor::div[@role='radiogroup'][1]")
                                except NoSuchElementException:
                                    logger.debug(f"Pass 2: Could not find common parent for {bad_input_label} to find alternatives.")
                            
                            alternative_options = []
                            if parent_group:
                                all_options_in_group = parent_group.find_elements(By.CSS_SELECTOR, "input[type='radio'], input[type='checkbox']")
                                alternative_options = [
                                    opt for opt in all_options_in_group 
                                    if opt.get_attribute("id") != bad_input_element.get_attribute("id") and \
                                       opt.get_attribute("aria-invalid") != "true" and \
                                       opt.is_displayed() and opt.is_enabled() # Ensure alternative is interactable
                                ]
                            
                            clicked_an_alternative = False
                            for alt_option in alternative_options:
                                alt_option_label = self._semantic_label(alt_option)
                                logger.info(f"Validation (Pass 2) – swapping invalid choice for '{bad_input_label}' with alternative '{alt_option_label}'.")
                                # Using JavaScript click as a more robust method for radio/checkboxes
                                self.driver.execute_script("arguments[0].click();", alt_option)
                                time.sleep(0.3) # Brief pause
                                
                                original_is_now_valid = bad_input_element.get_attribute("aria-invalid") != "true"
                                alt_is_selected_and_valid = alt_option.is_selected() and alt_option.get_attribute("aria-invalid") != "true"

                                if original_is_now_valid or alt_is_selected_and_valid:
                                    logger.info(f"Pass 2: Successfully swapped to an alternative valid option '{alt_option_label}'.")
                                    pass2_fixed_anything = True; clicked_an_alternative = True; break 
                                else:
                                    logger.warning(f"Pass 2: Clicked alternative '{alt_option_label}', but state not confirmed valid.")
                            if clicked_an_alternative: break 
                        except Exception as e_swap:
                            logger.debug(f"Pass 2: Couldn’t swap invalid option for {bad_input_label}: {e_swap}", exc_info=True)
                except Exception as e_outer_swap_loop:
                    logger.debug(f"Pass 2: Error in outer loop for swapping invalid options ({bad_input_css_selector}): {e_outer_swap_loop}", exc_info=True)
        
        if pass2_fixed_anything:
            logger.info("Validation errors handled in Pass 2 (swapped invalid-but-selected radio/checkbox).")
            return True

        logger.warning("No validation errors resolved by either Pass 1 or Pass 2.")
        return False

    def _check_and_handle_validation_errors(self, current_step_root_element=None) -> bool:
        # ... (This method's logic remains largely the same, but it calls the updated _handle_validation_errors)
        # Ensure _semantic_label is used if any direct label checks are done here.
        # For file uploads, the _handle_single_file_input now has improved confirmation.
        logger.debug("Checking for validation error messages...")
        fixed_any = False 
        try:
            root_element_for_check = current_step_root_element
            if root_element_for_check is None:
                try:
                    root_element_for_check = self.driver.find_element(By.CSS_SELECTOR, "div.jobs-easy-apply-modal__content")
                except NoSuchElementException:
                    logger.warning("Modal content not found for validation check, using self.driver as root.")
                    root_element_for_check = self.driver

            # File upload validation
            try:
                invalid_uploads = root_element_for_check.find_elements(
                    By.CSS_SELECTOR, "input[type='file'][aria-required='true'][aria-invalid='true']"
                )
                if invalid_uploads:
                    logger.info(f"Found {len(invalid_uploads)} invalid required file uploads.")
                    for upload_input_element in invalid_uploads:
                        if not upload_input_element.is_displayed() and not ("jobs-document-upload-file-input" in (upload_input_element.get_attribute('id') or "")):
                            continue # Skip non-displayed unless it's the known hidden pattern
                        
                        upload_label = self._semantic_label(upload_input_element)
                        logger.info(f"Validation - missing/invalid required file upload for '{upload_label}', attempting re-upload.")
                        self._handle_single_file_input(upload_input_element, upload_label) # Pass normalized label
                        time.sleep(0.5) 
                        if upload_input_element.get_attribute("value") and upload_input_element.get_attribute("aria-invalid") != "true":
                            logger.info(f"File input '{upload_label}' now has a value and is not invalid after validation handling.")
                            fixed_any = True
                        else:
                            logger.warning(f"File input '{upload_label}' still has no value or is invalid after validation attempt.")
            except Exception as e_upload_check:
                logger.debug(f"Error during invalid upload check or handling: {e_upload_check}")

            # Text-based error messages
            error_messages_found_text = False
            # ... (error_selectors and loop largely unchanged, but ensure _get_raw_text and _norm are used for text comparison if any)
            error_selectors = [
                (By.CSS_SELECTOR, ".artdeco-inline-feedback__message"),
                (By.CSS_SELECTOR, ".fb-feedback__message"),
                (By.CSS_SELECTOR, "p[role='alert']"),
                (By.XPATH, ".//*[contains(@class, 'error') and contains(@class, 'message')]"),
                (By.XPATH, ".//*[contains(text(), 'Please make a selection') or contains(text(), 'This field is required') or contains(text(), 'Please enter a valid')]") # Added more generic error text
            ]
            visible_error_texts = []
            for by_method, selector in error_selectors:
                try:
                    error_elements = root_element_for_check.find_elements(by_method, selector)
                    for err_el in error_elements:
                        if err_el.is_displayed():
                            err_text = self._norm(self._get_raw_text(err_el))
                            if err_text:
                                visible_error_texts.append(err_text)
                                error_messages_found_text = True
                except: pass
            
            if error_messages_found_text:
                unique_errors = list(set(visible_error_texts))
                logger.warning(f"Text-based validation error(s) detected on page: {unique_errors}")
                if self._handle_validation_errors(root_element_for_check): 
                    logger.info("Attempted to handle radio/checkbox validation errors based on text error presence.")
                    fixed_any = True 
                else:
                    logger.warning("Detected text-based validation errors, but _handle_validation_errors (for radio/checkbox) could not resolve them or found none to resolve.")
            
            if fixed_any:
                logger.info("Validation issues were addressed (file upload or radio/checkbox). Returning True.")
                return True
            else:
                # ... (logging for no errors fixed) ...
                return False
        except Exception as e:
            logger.error(f"Exception in _check_and_handle_validation_errors: {e}", exc_info=True)
            return False
