#!/bin/bash

# Define the folder path and file name
FOLDER_PATH="/home/debian/docker/selenium-tmdb/preprocess"
ENV_FILE="${FOLDER_PATH}/.env"

# Check if the selenium-tmdb Docker container is running
if [ $(docker ps -q -f name=selenium-tmdb) ]; then
    echo "selenium-tmdb Docker container is already running."
else
    # Refuse to start without a host-managed secrets file.
    # Secrets must NEVER be baked into the image — they are passed at runtime
    # via --env-file (see .dockerignore which excludes .env from the build context).
    if [ ! -f "$ENV_FILE" ]; then
        echo "ERROR: env file not found at $ENV_FILE" >&2
        echo "Create it from preprocess/.env.example and keep it outside the image." >&2
        exit 1
    fi

    # Start the selenium-tmdb container if it is not running
    cd "$FOLDER_PATH"
    docker build -t selenium-tmdb-python-app .
    # docker run -it --rm --network="host" --env-file "$ENV_FILE" -v $(pwd):/app --name selenium-tmdb selenium-tmdb-python-app
    docker run -d --rm --network="host" \
        --env-file "$ENV_FILE" \
        -v $(pwd):/app \
        --name selenium-tmdb \
        selenium-tmdb-python-app
    echo "selenium-tmdb Docker container started."
fi
