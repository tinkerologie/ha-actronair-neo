FROM mcr.microsoft.com/devcontainers/python:3.15

# Remove Yarn repository to fix GPG key verification issue
# The Yarn repo in the base image has an expired/missing GPG key
# We don't need Yarn for this project, so we can safely remove it
RUN rm -f /etc/apt/sources.list.d/yarn.list && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
