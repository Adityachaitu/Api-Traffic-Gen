import json
import os
import urllib
from operator import index

import exrex
import json_flatten
from lib.loggers.logger import report_logger
from lib.label_value_generator import generate_fake_data, mutate_label_value
import random
from lib.parsers import ede_parser


logger = report_logger()
def convert_parameter_body(param_json):
    '''
    Reads Request/Response JSON and converts it if it contains EDE metadata.
    Else, it returns JSON as it is.
    :param param_json: JSON as read from excel row
    :return:
    '''
    try:
        param_body = json.loads(param_json)
        if 'ede_info' in param_body:
            ede_param = ede_parser.create_parameter_body(input_json=param_body['ede_info'])
            return ede_param
        else:
            return param_body
    except Exception as e:
        logger.warning("Not a json param. Hence returning as same as the input")
        return param_json

class LabelParser:

    def __init__(self):
        self.req_unique = {}
        self.rsp_unique = {}
        self._generate_muatation_related_data()
        self._initialize_seed_values()
    def _increment_ssn_seed(self):
        """Method to increment ssn seed value."""
        ssn_seed_list = self.ssn_seed.split("-")
        ssn_seed_list[len(ssn_seed_list) - 1] = str(
            int(ssn_seed_list[len(ssn_seed_list) - 1]) + 1
        )
        self.ssn_seed = "-".join(ssn_seed_list)

    def _generate_muatation_related_data(self):
        """Method that generates mutation related data."""
        self.mutation_index = random.choice([0, 0.33, 0.5, 0.75, 1])
        self.no_of_literals = random.randint(1, 5)

    def _initialize_seed_values(self):
        """Method to intialize ssn and routing number seed value for sequence."""
        self.ssn_seed = generate_fake_data(
            "ssn", valid=True, count=1
        )[0]
        self.routing_num = generate_fake_data(
            "us-banking-info", valid=True, count=1
        )[0]

    def fetch_labels(self, label_name):
        """Method to get labels using faker module.

        :param label_name: str, name of the label
        :return str, label
        """
        label = None
        if label_name.strip().split("-")[0] == "valid":
            label_name = "-".join(label_name.strip().split("-")[1:])
            valid_bool = True
            labelled_data = generate_fake_data(
                label_name, valid=valid_bool, count=1
            )
        elif label_name.strip().split("-")[0] == "invalid":
            label_name = "-".join(label_name.strip().split("-")[1:])
            valid_bool = False
            labelled_data = generate_fake_data(
                label_name, valid=valid_bool, count=1
            )
        elif label_name.strip().split("-")[0] == "mutated":
            label_name = "-".join(label_name.strip().split("-")[1:])
            valid_bool = True
            labelled_data = mutate_label_value(
                label_name,
                valid_bool,
                1,
                self.mutation_index,
                self.no_of_literals
            )
        elif label_name.strip().split("-")[0] == "sequence":
            label_name = "-".join(label_name.strip().split("-")[1:])
            if label_name == "ssn":
                labelled_data = [self.ssn_seed]
                self._increment_ssn_seed()
            if label_name == "us-banking-info":
                labelled_data = [self.routing_num]
                self.routing_num = str(
                    int(self.routing_num) + 1
                )
        elif label_name.strip().split(":")[0] == "regex":
            label_name = "".join(label_name.strip().split(":")[1:])
            labelled_data = [exrex.getone(label_name)]

        elif "<regex:" in label_name:
            logger.debug("Fetchin label for graphql")
            import re  # importing only when needed
            def replace_placeholder(match):
                regex_pattern = match.group(1)
                return exrex.getone(regex_pattern)

            query = re.sub(r"<regex:([^>]+)>", replace_placeholder, label_name)
            labelled_data = [query]

        elif label_name.strip().split("-")[0] == "random":
            label_name = "-".join(label_name.strip().split("-")[1:])

            labelled_data = generate_fake_data(
                label_name, count=1
            )

        if len(labelled_data) == 0:
            logger.debug("Please enter a valid label name in template")
        return labelled_data[0]

    def _parse_templates_and_enter_value(self, template_json, label_data_dict={}, unique_values={}):
        """Method for parsing templates and substituting them with labels.

        :param template_json: json, request or response body strings.
        :return json, json with labels.
        """
        # print(f"unique_values: {unique_values}")
        flattened_json = json_flatten.flatten(template_json)
        for key, value in flattened_json.items():
            count = 15
            if isinstance(value, str):
                unique_values.setdefault(key, [])
                if (value.startswith('gql<') and value.endswith('>gql')) or (value[0] == "<" and value[len(value) - 1] == ">"):
                    label_name = value[4:len(value) - 4] if value.startswith('gql<') else value[1:len(value) - 1]
                    label = self.fetch_labels(label_name)
                    while label in unique_values[key] and count != 0:
                        label = self.fetch_labels(label_name)
                        count -= 1
                    unique_values[key].append(label)
                    flattened_json[key] = label
                elif value[0] == "$" and value[len(value) - 1] == "$" and label_data_dict:
                    label_value = label_data_dict.get('label_key', {}).get('values', [])
                    while label_value in unique_values[key] and count != 0:
                        label_value = label_data_dict.get('label_key', {}).get('values', [])
                        count -= 1
                    unique_values[key].append(label_value)
                    flattened_json[key] = label_value[0]
                    label_value.remove(flattened_json[key])
        unflattened_labelled_json = json_flatten.unflatten(flattened_json)
        return unflattened_labelled_json

    def _parse_header_and_enter_value(self,req_header):
        while "<" in req_header:
            s_index = req_header.index("<")
            e_index = req_header.index(">")
            req_header = (req_header[0:s_index] + str(self.fetch_labels(req_header[s_index + 1:e_index])) + req_header[e_index + 1:])
        return req_header

    def _parse_url_and_query_and_enter_value(self, url):
        while "<" in url:
            s_index = url.index("<", 1)
            e_index = url.index(">", 1)
            # url = url[0:s_index] + self.fetch_labels(url[s_index + 1:e_index]) + url[e_index + 1:]
            url = (url[0:s_index] + urllib.parse.quote_plus(str(self.fetch_labels(url[s_index + 1:e_index]))) + url[e_index + 1:])
        return url

    def parse_label(self, url, reqbody, respbody, req_header):
        if len(reqbody) > 0:
            reqbody = self._parse_templates_and_enter_value(template_json=convert_parameter_body(reqbody),
                                                       unique_values=self.req_unique)
        if len(respbody) > 0:
            respbody = self._parse_templates_and_enter_value(template_json=convert_parameter_body(respbody),
                                                        unique_values=self.rsp_unique)
        req_header = self._parse_header_and_enter_value(req_header)
        url = self._parse_url_and_query_and_enter_value(url)
        return url, reqbody, respbody, req_header

if __name__ == "__main__":
    obj = LabelParser()
    url,req,res,header = obj.parse_label("sda/sfsd/fasfa?Name=<valid-full-name>&Name2=<valid-email>",'{"name":"<valid-name>"}','{"name":"<valid-name>"}','{"x-detail":"<valid-name>,<valid-email>"}')
    print(url)
    print(req)
    print(res)
    print(header)
