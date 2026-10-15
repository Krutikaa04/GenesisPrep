FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
WORKDIR /app
# Standard library only: nothing to download, so the build works with the network disabled.
COPY deadbits/ deadbits/
COPY salvage .
RUN chmod +x salvage
ENTRYPOINT ["./salvage"]
