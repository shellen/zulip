# Zulip's OpenAPI-based API documentation system is documented at
#   https://zulip.readthedocs.io/en/latest/documentation/api.html
#
# This file contains the top-level logic for testing the cURL examples
# in Zulip's API documentation; the details are in
# zerver.openapi.curl_param_value_generators.

import html
import json
import os
import re
import shlex
import subprocess

import markdown
from django.conf import settings
from zulip import Client

from zerver.models import get_realm
from zerver.openapi import markdown_extension
from zerver.openapi.curl_param_value_generators import (
    AUTHENTICATION_LINE,
    assert_all_helper_functions_called,
)
from zerver.openapi.openapi import get_endpoint_from_operationid


def test_generated_curl_examples_for_success(client: Client) -> None:
    default_authentication_line = f"{client.email}:{client.api_key}"
    # A limited Markdown engine that just processes the code example syntax.
    realm = get_realm("zulip")
    md_engine = markdown.Markdown(
        extensions=[markdown_extension.makeExtension(api_url=realm.uri + "/api")]
    )

    # We run our curl tests in alphabetical order (except that we
    # delay the deactivate-user test to the very end), since we depend
    # on "add" tests coming before "remove" tests in some cases.  We
    # should try to either avoid ordering dependencies or make them
    # very explicit.
    rest_endpoints_path = os.path.join(
        settings.DEPLOY_ROOT, "templates/zerver/help/include/rest-endpoints.md"
    )
    rest_endpoints_raw = open(rest_endpoints_path).read()
    ENDPOINT_REGEXP = re.compile(r"/api/\s*(.*?)\)")
    endpoint_list = sorted(set(re.findall(ENDPOINT_REGEXP, rest_endpoints_raw)))

    for endpoint in endpoint_list:
        article_name = endpoint + ".md"
        file_name = os.path.join(settings.DEPLOY_ROOT, "templates/zerver/api/", article_name)
        curl_commands_to_test = []

        if os.path.exists(file_name):
            f = open(file_name)
            for line in f:
                # A typical example from the Markdown source looks like this:
                #     {generate_code_example(curl, ...}
                if line.startswith("{generate_code_example(curl"):
                    curl_commands_to_test.append(line)
        else:
            # If the file doesn't exist, then it has been
            # deleted and its page is generated by the
            # template. Thus, the curl example would just
            # a single one following the template's pattern.
            endpoint_path, endpoint_method = get_endpoint_from_operationid(endpoint)
            endpoint_string = endpoint_path + ":" + endpoint_method
            command = f"{{generate_code_example(curl)|{endpoint_string}|example}}"
            curl_commands_to_test.append(command)

        for line in curl_commands_to_test:
            # To do an end-to-end test on the documentation examples
            # that will be actually shown to users, we use the
            # Markdown rendering pipeline to compute the user-facing
            # example, and then run that to test it.

            # Set AUTHENTICATION_LINE to default_authentication_line.
            # Set this every iteration, because deactivate_own_user
            # will override this for its test.
            AUTHENTICATION_LINE[0] = default_authentication_line

            curl_command_html = md_engine.convert(line.strip())
            unescaped_html = html.unescape(curl_command_html)
            curl_regex = re.compile(r"<code>curl\n(.*?)</code>", re.DOTALL)
            commands = re.findall(curl_regex, unescaped_html)

            for curl_command_text in commands:
                curl_command_text = curl_command_text.replace(
                    "BOT_EMAIL_ADDRESS:BOT_API_KEY", AUTHENTICATION_LINE[0]
                )

                print("Testing {} ...".format(curl_command_text.split("\n")[0]))

                # Turn the text into an arguments list.
                generated_curl_command = [x for x in shlex.split(curl_command_text) if x != "\n"]

                response_json = None
                response = None
                try:
                    # We split this across two lines so if curl fails and
                    # returns non-JSON output, we'll still print it.
                    response_json = subprocess.check_output(
                        generated_curl_command, universal_newlines=True
                    )
                    response = json.loads(response_json)
                    assert response["result"] == "success"
                except (AssertionError, Exception):
                    error_template = """
Error verifying the success of the API documentation curl example.

File: {file_name}
Line: {line}
Curl command:
{curl_command}
Response:
{response}

This test is designed to check each generate_code_example(curl) instance in the
API documentation for success. If this fails then it means that the curl example
that was generated was faulty and when tried, it resulted in an unsuccessful
response.

Common reasons for why this could occur:
    1. One or more example values in zerver/openapi/zulip.yaml for this endpoint
       do not line up with the values in the test database.
    2. One or more mandatory parameters were included in the "exclude" list.

To learn more about the test itself, see zerver/openapi/test_curl_examples.py.
"""
                    print(
                        error_template.format(
                            file_name=file_name,
                            line=line,
                            curl_command=generated_curl_command,
                            response=response_json
                            if response is None
                            else json.dumps(response, indent=4),
                        )
                    )
                    raise

    assert_all_helper_functions_called()
