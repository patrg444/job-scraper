import yaml
import os
import openai # Import the base module

# Check if OpenAI library is available and usable
try:
    from openai import OpenAI # Client class
    # Specific error classes are attributes of the openai module in v1.x
    # We will reference them as openai.APIError, openai.AuthenticationError etc.
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("OpenAI library is not installed or the OpenAI client class could not be imported.")
    print("Please ensure it's installed (e.g., pip install openai>=1.0.0) and accessible.")

def load_api_key_from_config(config_path="lite_linkedin_bot/config.yaml"):
    """Loads the OpenAI API key from the configuration file."""
    try:
        effective_config_path = config_path
        if not os.path.exists(effective_config_path):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            abs_config_path = os.path.join(script_dir, os.path.basename(config_path))
            print(f"Config file not found at relative path: {config_path}. Trying path relative to script dir: {abs_config_path}")
            effective_config_path = abs_config_path

        if not os.path.exists(effective_config_path):
            proj_root_config_path = os.path.join(os.getcwd(), config_path)
            if os.path.exists(proj_root_config_path):
                effective_config_path = proj_root_config_path
            else:
                print(f"Error: Configuration file not found at {config_path}, {abs_config_path}, or {proj_root_config_path}")
                return None
        
        print(f"Attempting to load config from: {effective_config_path}")
        with open(effective_config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config.get('openai_api_key')
    except FileNotFoundError:
        print(f"Error: Configuration file not found.")
        return None
    except yaml.YAMLError as e:
        print(f"Error parsing YAML configuration file: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while loading config: {e}")
        return None

def test_openai_api():
    """Tests the OpenAI API with a simple chat completion request using v1.x.x syntax."""
    if not OPENAI_AVAILABLE:
        return

    api_key = load_api_key_from_config()

    if not api_key:
        print("OpenAI API key not found in config.yaml or config file could not be read.")
        print("Please ensure 'openai_api_key' is set in lite_linkedin_bot/config.yaml")
        return

    try:
        client = OpenAI(api_key=api_key)
        print(f"OpenAI client initialized. API key loaded: {api_key[:5]}...{api_key[-4:]}")

        print("\nAttempting to make a test call to OpenAI API (v1.x.x syntax)...")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello, world! This is a test."}
            ]
        )
        print("\nAPI Call Successful!")
        print("Response:")
        if response.choices and len(response.choices) > 0:
            print(response.choices[0].message.content.strip())
        else:
            print("No choices found in response.")
            print("Full response object:", response)

    except openai.AuthenticationError as e:
        print("\nOpenAI API Error: Authentication failed. Please check your API key.")
        print(f"Details: {e}")
    except openai.RateLimitError as e:
        print("\nOpenAI API Error: Rate limit exceeded. Please check your usage or wait and try again.")
        print(f"Details: {e}")
    except openai.BadRequestError as e: # Changed from InvalidRequestError
        print("\nOpenAI API Error: Invalid request (BadRequestError). This might be due to an issue with the prompt or parameters.")
        print(f"Details: {e}")
    except openai.APIError as e: # More general API error
        print("\nOpenAI API Error: An issue occurred with the API call.")
        print(f"Details: {e}")
    except Exception as e:
        print(f"\nAn unexpected error occurred during the OpenAI API call: {e}")

if __name__ == "__main__":
    test_openai_api()
