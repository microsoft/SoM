from gradio_client import Client

client = Client("http://3.237.36.123:6092")
result = client.predict(
        {
            "background": "https://raw.githubusercontent.com/gradio-app/gradio/main/test/test_files/bus.png",
        },           # filepath  in 'parameter_1' Image component
        2.5,         # float (numeric value between 1 and 3) in 'Granularity' Slider component
        "Automatic", # Literal['Automatic', 'Interactive']  in 'Segmentation Mode' Radio component
        0.5,         # float (numeric value between 0 and 1) in 'Mask Alpha' Slider component
        "Number",    # Literal['Number', 'Alphabet']  in 'Mark Mode' Radio component
        ["Mark"],    # List[Literal['Mask', 'Box', 'Mark']]  in 'Annotation Mode' Checkboxgroup component
        api_name="/inference"
)
print(result)
