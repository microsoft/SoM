deploy:   
  gradio deploy


cp cId file="app.py":
  docker cp {{file}} {{cId}}:/usr/src/app