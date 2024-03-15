FROM nvidia/cuda:12.3.1-devel-ubuntu22.04

# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
      python3-pip python3-dev git ninja-build wget \
      ffmpeg libsm6 libxext6 \
      openmpi-bin libopenmpi-dev && \
    ln -sf /usr/bin/python3 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the current directory contents into the container at /usr/src/app
COPY . .

ENV FORCE_CUDA=1

# Upgrade pip
RUN python -m pip install --upgrade pip

# Install Python dependencies
RUN pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu123 \
    && pip install git+https://github.com/UX-Decoder/Segment-Everything-Everywhere-All-At-Once.git@33f2c898fdc8d7c95dda014a4b9ebe4e413dbb2b \
    && pip install git+https://github.com/facebookresearch/segment-anything.git \
    && pip install git+https://github.com/UX-Decoder/Semantic-SAM.git@package \
    && cd ops && bash make.sh && cd .. \
    && pip install mpi4py \
    && pip install openai \
    && pip install gradio==4.17.0

# Download pretrained models
RUN sh download_ckpt.sh

# Make port 6092 available to the world outside this container
EXPOSE 6092

# Make Gradio server accessible outside 127.0.0.1
ENV GRADIO_SERVER_NAME="0.0.0.0"

RUN chmod +x /usr/src/app/entrypoint.sh
CMD ["/usr/src/app/entrypoint.sh"]
