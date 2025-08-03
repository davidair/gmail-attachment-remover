#
# The MIT License
#
# Copyright 2025 David Airapetyan
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import click
import os
import re
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from base64 import urlsafe_b64decode, urlsafe_b64encode
from email import message_from_bytes, policy
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google_auth_oauthlib.flow import InstalledAppFlow

from pathlib import Path

# Scopes for Gmail API
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def sanitize(email_address):
    """
    Sanitizes email address to make it usable as a directory name.
    """
    return re.sub(r'[<>:"/\\|?*@\.]', "_", email_address)


def sanitize_path(filename):
    """
    Sanitize filename to be safe across macOS, Windows, and Linux.
    Removes directory traversal and invalid characters.
    """
    # Remove directory traversal
    filename = os.path.basename(filename)

    # Replace unsafe characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', filename)

    # Optional: trim overly long filenames
    return filename[:255]


def get_user_cache(email_address):
    """
    Create an email cache under local user directory.
    This also serves as backup for emails that end up being rewritten.
    """
    cache_path = (
        Path(os.path.expanduser("~")) / "cached_emails" / sanitize(email_address)
    )
    cache_path.mkdir(parents=True, exist_ok=True)
    return cache_path


def authenticate_gmail():
    """
    Authenticates.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.json"):
        print("Reading existing credentials from token.json")
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired creds...")
            creds.refresh(Request())
        else:
            print("Creating new signin flow...")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    if not creds:
        raise "Could not load credentials - check README.md for instructions"
    return build("gmail", "v1", credentials=creds)


def fetch_email(service, email_address, message_id):
    """
    Fetches an email, caching it locally.
    """
    print(f"Fetching email with id = {message_id}")
    user_cache = get_user_cache(email_address)
    cached_path = user_cache / Path(message_id + ".txt")

    if cached_path.exists() and cached_path.is_file():
        print(f"Reading from cached location: {cached_path}")
        with cached_path.open("rb") as file:
            raw_message = file.read()
            return message_from_bytes(raw_message, policy=policy.default)

    message = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="raw")
        .execute()
    )
    raw_message = urlsafe_b64decode(message["raw"])
    decoded_message = message_from_bytes(raw_message, policy=policy.default)
    with cached_path.open("wb") as file:
        file.write(raw_message)
    return decoded_message


def list_attachments_in_message(original_message):
    """
    List attachments in an email, including their filenames and sizes in bytes.
    """
    attachments = []

    for part in original_message.iter_attachments():
        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        size = len(payload) if payload else 0

        attachments.append(
            {
                "filename": filename if filename else "Unnamed attachment",
                "size_bytes": size,
            }
        )

    return attachments


def extract_attachments_in_message(original_message, cached_message_attachments_directory):
    """
    Extract and save attachments from the email to the given directory,
    ensuring sanitized and non-conflicting filenames.
    """
    # Keep track of filenames to handle duplicates
    seen_filenames = {}

    for part in original_message.iter_attachments():

        # Create directory if needed
        os.makedirs(cached_message_attachments_directory, exist_ok=True)

        raw_filename = part.get_filename()
        if not raw_filename:
            continue  # Skip unnamed attachments

        # Sanitize filename
        clean_filename = sanitize_path(raw_filename)

        # Handle duplicates by appending _1, _2 etc., respecting file extension
        name, ext = os.path.splitext(clean_filename)
        count = seen_filenames.get(clean_filename, 0)

        if count > 0:
            clean_filename = f"{name}_{count}{ext}"

        seen_filenames[raw_filename] = count + 1

        # Save to disk
        filepath = os.path.join(cached_message_attachments_directory, clean_filename)
        payload = part.get_payload(decode=True)
        if payload:
            print(f"Saving {filepath}")
            with open(filepath, 'wb') as f:
                f.write(payload)


def remove_attachments_from_message(original_message):
    """
    Remove attachments from the email.
    """
    # Extract headers and body
    email_body = original_message.get_body(preferencelist=("plain", "html"))
    email_text = email_body.get_content() if email_body else ""

    # Create a new email without attachments
    new_message = MIMEMultipart()
    for key in original_message.keys():
        if key == "Content-Type" or key == "MIME-Version":
            continue
        new_message[key] = original_message[key]
    new_message.attach(MIMEText(email_text, "plain"))

    return new_message


def reinsert_email(service, modified_message):
    """
    Encode and reinsert the modified email, preserving date thanks to internalDateSource=dateHeader.
    """
    print(f"Reinserting the email")
    raw_message = urlsafe_b64encode(modified_message.as_bytes()).decode()
    return (
        service.users()
        .messages()
        .insert(userId="me", body={"raw": raw_message}, internalDateSource="dateHeader")
        .execute()
    )


def delete_email(service, message_id):
    """
    Immediately deletes an email.
    Requires full scope: https://developers.google.com/gmail/api/auth/scopes
    """
    print(f"Deleting email with id = {message_id}")
    service.users().messages().delete(userId="me", id=message_id).execute()


def trash_email(service, message_id):
    """
    Moves the specified email to the trash instead of permanently deleting it.
    """
    print(f"Trashing email with id = {message_id}")
    service.users().messages().trash(userId="me", id=message_id).execute()


def find_messages(service, query):
    """
    Finds all messages matching a Gmail query.
    """
    response = service.users().messages().list(userId="me", q=query).execute()
    messages = response.get("messages", [])
    return messages


def get_message_headers(message):
    """
    Returns a list of "interesting" headers that help identify the message.
    """
    headers = []
    for key in message.keys():
        if key not in ["Subject", "Delivered-To", "From", "To", "CC", "Date"]:
            continue
        headers.append(f"{key} = {message[key]}")
    return headers


def list_email_attachments(service, email_address, message_id):
    """
    Lists attachments in an email
    - Fetches the email (or uses local cache)
    - Lists attachments
    """
    mail = fetch_email(service, email_address, message_id)
    print(list_attachments_in_message(mail))


def extract_email_attachments(service, email_address, message_id):
    """
    Extracts attachments in an email
    - Fetches the email (or uses local cache)
    - Saves every attachment under the local cache
    """
    mail = fetch_email(service, email_address, message_id)
    user_cache = get_user_cache(email_address)
    cached_message_attachments_directory = user_cache / Path(message_id)

    extract_attachments_in_message(mail, cached_message_attachments_directory)


def rewrite_email_stripping_attachments(
    service, email_address, message_id, make_changes
):
    """
    Rewrites the email stripping attachments:
    - Fetches the email (caching it locally, which can be used for backup purposes)
    - Removes attachments
    - Trashes the original email
    - Re-inserts email with original date
    """
    mail = fetch_email(service, email_address, message_id)
    updated_message = remove_attachments_from_message(mail)
    if not make_changes:
        print(
            f"Would have remove attachments from {get_message_headers(updated_message)}"
        )
        print("To actually make changes, pass in the --make_changes flag")
        return
    trash_email(service, message_id)
    reinsert_email(service, updated_message)


def get_service_and_email_address():
    """
    Helper method to initialize Gmail service and get current user id.
    """
    service = authenticate_gmail()
    print("Fetching current user's address...")
    email_address = service.users().getProfile(userId="me").execute()["emailAddress"]
    print(f"Address fetched: {email_address}")
    return (service, email_address)


@click.group()
def cli():
    """
    Initialize Click.
    """
    pass


@click.command(
    help="Finds messages given a Gmail query, such as 'has:attachment larger:20MB'"
)
@click.argument("query")
@click.option("--output-csv", "-o", is_flag=True, help="Output comma-separated IDs")
def find_emails(query, output_csv):
    """
    Finds all message ids matching a query.
    """
    service = authenticate_gmail()
    messages = find_messages(service, query)

    if output_csv:
        click.echo(",".join([x["id"] for x in messages]))
    else:
        click.echo(f"Query: {query}\nResults: {messages}")


@click.command(
    help="Fetches emails and caches them locally. Takes comma-separated list of message ids."
)
@click.argument("message_ids")
def fetch_emails(message_ids):
    """
    Fetches all messages for a list of message ids.
    """

    service, email_address = get_service_and_email_address()

    ids = message_ids.split(",")
    for id in ids:
        message = fetch_email(service, email_address, id)
        for header in get_message_headers(message):
            print(header)
        print()


@click.command(
    help="Removes attachments from emails. Takes comma-separated list of message ids as input."
)
@click.argument("message_ids")
@click.option("--make-changes", is_flag=True, help="Dry run mode (default: True)")
def remove_attachments(message_ids, make_changes):
    """
    Removes attachments from messages specified by a list of ids.
    """

    service, email_address = get_service_and_email_address()

    ids = message_ids.split(",")
    for id in ids:
        rewrite_email_stripping_attachments(service, email_address, id, make_changes)


@click.command(
    help="Lists attachments in emails. Takes comma-separated list of message ids as input."
)
@click.argument("message_ids")
def list_attachments(message_ids):
    """
    Lists attachments in messages specified by a list of ids.
    """

    service, email_address = get_service_and_email_address()

    ids = message_ids.split(",")
    for id in ids:
        list_email_attachments(service, email_address, id)


@click.command(
    help="Extracts attachments from emails. Takes comma-separated list of message ids as input."
)
@click.argument("message_ids")
def extract_attachments(message_ids):
    """
    Extracts attachments from messages specified by a list of ids and saves them in the cache directory.
    """

    service, email_address = get_service_and_email_address()

    ids = message_ids.split(",")
    for id in ids:
        extract_email_attachments(service, email_address, id)


cli.add_command(find_emails)
cli.add_command(fetch_emails)
cli.add_command(remove_attachments)
cli.add_command(list_attachments)
cli.add_command(extract_attachments)

if __name__ == "__main__":
    cli()
