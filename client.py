"""
This module provides a command-line interface to interact with the SoM server.

The server URL is printed during deployment via `python deploy.py run`.

Usage:
    python client.py "http://<server_ip>:6092"
"""

import fire
from gradio_client import Client
from loguru import logger

def predict(server_url: str):
    """
    Makes a prediction using the Gradio client with the provided IP address.

    Args:
        server_url (str): The URL of the SoM Gradio server.
    """
    client = Client(server_url)
    result = client.predict(
        {
            "background": "https://raw.githubusercontent.com/gradio-app/gradio/main/test/test_files/bus.png",
        },           # filepath in 'parameter_1' Image component
        2.5,         # float (numeric value between 1 and 3) in 'Granularity' Slider component
        "Automatic", # Literal['Automatic', 'Interactive'] in 'Segmentation Mode' Radio component
        0.5,         # float (numeric value between 0 and 1) in 'Mask Alpha' Slider component
        "Number",    # Literal['Number', 'Alphabet'] in 'Mark Mode' Radio component
        ["Mark"],    # List[Literal['Mask', 'Box', 'Mark']] in 'Annotation Mode' Checkboxgroup component
        api_name="/inference"
    )
    logger.info(result)

if __name__ == "__main__":
    fire.Fire(predict)
