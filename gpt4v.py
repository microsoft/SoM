import os
import base64
import requests

# Get OpenAI API Key from environment variable
api_key = os.environ["OPENAI_API_KEY"]
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

metaprompt = '''
- You always generate the answer in markdown format. For any marks mentioned in your answer, please highlight them in a red color and bold font.
'''    

# Function to encode the image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def prepare_inputs(message):

    # Path to your image
    image_path = "temp.jpg"

    # Getting the base64 string
    base64_image = encode_image(image_path)

    payload = {
        "model": "gpt-4-vision-preview",
        "messages": [
        # {
        #     "role": "system",
        #     "content": [
        #         metaprompt
        #     ]
        # }, 
        {
            "role": "user",
            "content": [
            {
                "type": "text",
                "text": message, 
            },
            {
                "type": "image_url",
                "image_url": {
                "url": f"data:image/jpeg;base64,{base64_image}"
                }
            }
            ]
        }
        ],
        "max_tokens": 300
    }

    return payload

def request_gpt4v(message):
    payload = prepare_inputs(message)
    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    res = response.json()['choices'][0]['message']['content']
    return res
