# Gmail Attachment Remover

As the Gmail inbox is growing larger, it can be necessary to remove big items to save space. However, it's ofen useful to only remove attachments without the actual emails.
However, Gmail does not offer that functionality.

Based on the discussion in https://stackoverflow.com/questions/46434390/remove-an-attachment-of-a-gmail-email-with-google-apps-script, this tool offers the ability to do this.

## Implementation details

Gmail messages are immutable - this means that they cannot be modified, only deleted. Email attachments are always stored as part of the email text, in BASE64 format, per RFC 2045 - MIME (Multipurpose Internet Mail Extensions).
In order to achieve the effect of "removing" attachments, one has to:

1. Download the full email (message)
2. Re-upload the email stripping the attachment payload, preserving the original email timestamp
3. Delete the original email from Gmail

This tool provides the functionality to find messages, download them and re-upload them without attachments.

Note that the download messages functionality can also serve as a backup function.

## Setup

Make sure you have pyenv installed. To install pyenv:

- Windows: `choco install pyenv-win`
- MacOS: `brew install pyenv`

Make sure pyenv is up to date with `pyenv update`.

This project has been tested with Python 3.13.2.
It can be installed with pyenv via `pyenv install 3.13.2`.

### Install GCloud CLI

Follow the instructions here:
https://cloud.google.com/sdk/docs/install#installation_instructions

Make sure the "gcloud" command works from the command line before proceeding to next steps.

### Initialize GCloud

```
gcloud init
```

### Create the project

```
gcloud projects create gmail-attachment-remover
gcloud config set project gmail-attachment-remover
```

### Enable the Gmail API

```
gcloud services enable gmail.googleapis.com
```

### Create credentials

- Navigate to https://console.cloud.google.com/auth/overview and follow the instructions to configure auth.
- Navigate to https://console.cloud.google.com/auth/clients and create a "Desktop app" client.
- When offered, download the json file and save it as "credentials.json" in this project's root directory.
- Make sure to add your email address as a test user under Audiences!

### Create a virtual environment

```
python -m venv .venv
```

### Activate the virtual environment

Windows: `.venv\Scripts\activate.bat`
MacOS and Linux: `source ./.venv/bin/activate`

### Install pip-tools

```
pip install pip-tools
```

### Compile and install the requirements

```
pip-compile
pip-sync
```

# Usage

## Finding emails

First, you need to find the ids of emails matching selection criteria using Gmail search queries:

```
python attachment_remover.py find-emails QUERY
```

For example, the following command will find all emails that have attachments larger that 20MB:

```
python attachment_remover.py find-emails "has:attachment larger:20MB"
```

Use the `--output-csv` flag to output comma-separated list of message ids.

## Saving emails

To download emails, run the following command:

```
python attachment_remover.py fetch-emails MESSAGE_ID[,MESSAGE_ID,MESSAGE_ID,...]
```

For example, if we wanted to download two messsages with ids 123 and 456, we'd call this:

```
python attachment_remover.py fetch-emails 123,456
```

The emails are saved under the user profile, in the cached_email directory:

- Windows: %USERPROFILE%\cached_emails
- Linux/MacOS: ~/cached_emails

##  Removing attachments

Once the emails have been downloaded, the following command will remove attachments in the Gmail inbox:

```
python attachment_remover.py remove-attachments MESSAGE_ID[,MESSAGE_ID,MESSAGE_ID,...]
```

For example, if we wanted to remove attachments for two messsages with ids 123 and 456, we'd call this:

```
python attachment_remover.py remove-attachments 123,456
```

Note that by default, this command will run in "dry-run" mode, i.e. it will print the list of changes but will not actually do them.
Pass the  --make_changes flag to actually make changes.

##  Listing attachments

Once the emails have been downloaded, the following command will list attachments in the Gmail inbox:

```
python attachment_remover.py list-attachments MESSAGE_ID[,MESSAGE_ID,MESSAGE_ID,...]
```

For example, if we wanted to list attachments for two messsages with ids 123 and 456, we'd call this:

```
python attachment_remover.py list-attachments 123,456
```
