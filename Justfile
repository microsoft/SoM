deploy:   
  gradio deploy


cp cId file="app.py":
  docker cp {{cId}} {{file}}