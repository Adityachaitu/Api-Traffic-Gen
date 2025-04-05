import json
import yaml
import json
import os
import re
import xlsxwriter
import random
from faker import Faker

from lib.im_environment import ImEnvironment
from lib.SpecTrafficGenerator.OpenApiSpecGenerator import Resolver
from lib.parsers.xlsx_parser import XlSXParser
from lib.trafficgenerator.traffic_generator import TrafficGenerator
from lib.loggers.logger import report_logger

logger = report_logger()

CONFIG_FILE = "../../config/config.yaml"
HEADER_LIST = ["test_id", "Input_URL", "Input_Host", "Input_Method", "Input_Rsp_Code", "Input_Req_Header", "Input_Req_Body", "Input_Rsp_Body"]
CONTENT_TYPE_LIST = ["application/json", "application/soap+xml", "application/x-www-form-urlencoded", "application/xml", "*/*", "text/json", "text/plain", "application/*+json"]


class OpenApiSpecParser(object):
    def __init__(self, swagger_file):
        self.specs = None
        self.ImObj = ImEnvironment(os.path.join(os.path.dirname(__file__), CONFIG_FILE))
        self.workbook = xlsxwriter.Workbook(f"./OutputFiles/{swagger_file.split('/')[-1]}.xlsx")
        self.worksheet = self.workbook.add_worksheet("discovery_engine")

        with open(os.path.join(os.path.dirname(__file__), "key_patterns.json")) as f:
            self.label_regex = json.load(f)

        self.swagger_file = swagger_file

    def resolve_composite_schema(self, schema) :
        if type(schema) is not dict:
            return schema
        if "oneOf" in schema :
            return self.resolve_composite_schema(random.choice(schema["oneOf"]))
        elif "anyOf" in schema :
            return self.resolve_composite_schema(random.choice(schema["anyOf"]))
        elif "allOf" in schema :
            merged_schema = { }
            for sub_schema in schema["allOf"] :
                resolved_sub_schema = self.resolve_composite_schema(sub_schema)
                for key, value in resolved_sub_schema.items() :
                    if key == "properties" and key in merged_schema :
                        merged_schema[key].update(value)
                    else :
                        merged_schema[key] = value
            return merged_schema
        elif isinstance(schema, dict) :
            return { key : self.resolve_composite_schema(value) for key, value in schema.items() }
        return schema

    def generate_body_from_schema(self, schema, name="<random-string>") :
        if not schema:
            return dict()

        schema = self.resolve_composite_schema(schema)

        if "enum" in schema :
            return random.choice(schema["enum"])

        elif schema.get("type") == "array" :
            item_schema = schema.get("items", dict())
            return [self.generate_body_from_schema(item_schema, name)]

        elif schema.get("type") == "object" :
            properties = schema.get("properties", dict())
            return dict({ key : self.generate_body_from_schema(val, (
                (self.get_label_name(key)) if self.get_label_name(key) else f"{key}"
            )) for key, val in properties.items() })

        elif schema.get("type") == "integer":
            return random.randint(0, 9999999999)

        elif schema.get("type") == "number":
            return random.uniform(-9999, 999999)

        elif "maxLength" in schema.keys():
            return Faker('en_US').pystr(schema.get("maxLength"), schema.get("maxLength"))

        return f"<random-{schema.get('type', 'string')}>"

    def extract_request_body(self, request_body, content_type):
        if not request_body:
            return dict()

        content = request_body.get("content", dict())

        for cnt_type, schema_info in content.items():
            if cnt_type == content_type:
                schema = schema_info.get("schema", dict())
                return self.generate_body_from_schema(schema)

        return dict()

    def extract_path_params(self, api, api_body):
        if "{" in api and "}" in api:
            path_param = api.split("{", 1)[1].split("}", 1)[0]

            have_enum = False

            if self.get_label_name(path_param):
                api = api.replace("{" + path_param + "}", self.get_label_name(path_param))

            else:
                for method, method_info in api_body.items():
                    if method == "parameters":
                        continue

                    for param in method_info["parameters"]:
                        if param["name"] == path_param:
                            if "schema" in param.keys():
                                data_type = param["schema"]["type"]

                                if "enum" in param["schema"].keys():
                                    have_enum = True
                                    value = random.choice(param["schema"]["enum"])
                                break

                            else:
                                data_type = param["type"]

                                if "enum" in param.keys():
                                    have_enum = True
                                    value = random.choice(param["enum"])
                    break

                if not have_enum:
                    api = api.replace("{" + str(path_param) + "}", "<random-" + data_type + ">")
                else:
                    api = api.replace("{" + str(path_param) + "}", str(value))

        if "{" in api and "}" in api:
            return self.extract_path_params(api, api_body)

        return api

    def extract_params(self, methods):
        query_params = []
        headers = dict()
        req_body = dict()
        form_data = dict()

        if "parameters" in methods:
            for param in methods["parameters"]:
                param_name = param.get("name", "param")
                param_schema = self.resolve_composite_schema(param.get("schema", dict()))
                param_type = (param["type"] if "type" in param.keys() else param_schema.get("type", "string"))

                have_enum = False

                if "enum" in param_schema.keys() or "enum" in param.keys():
                    have_enum = True
                    enum_array = (param["enum"] if "enum" in param.keys() else param_schema["enum"])

                elif param_type == "string" and "maxLength" in param_schema.keys():
                    str_len = param_schema["maxLength"]
                    min_str_len = (param_schema["minLength"] if "minLength" in param_schema.keys() else str_len-1)

                if param.get("in") == "query":
                    if param_type == "array":
                        item_type = param_schema.get("items", dict()).get("type", "string")
                        if not have_enum:
                            if item_type == "string" and "maxLength" in param_schema.keys() :
                                query_params.append(f"[{param_name}={Faker('en_US').pystr(min_str_len, str_len)}]")
                            else:
                                query_params.append(
                                    f"{param_name}=[{self.get_label_name(param_name)}]" if self.get_label_name(
                                        param_name) else f"{param_name}=[<random-{item_type}>]")
                        else:
                            query_params.append(
                                f"{param_name}={random.choice(enum_array)}"
                            )

                    else:
                        if not have_enum:
                            if param_type == "string" and "maxLength" in param_schema.keys() :
                                query_params.append(f"{param_name}={Faker('en_US').pystr(min_str_len, str_len)}")
                            else:
                                query_params.append(f"{param_name}={self.get_label_name(param_name)}" if self.get_label_name(
                                    param_name) else f"{param_name}=<random-{param_type}>")

                        else:
                            query_params.append(f"{param_name}={random.choice(enum_array)}")

                elif param.get("in") == "header":
                    if param_type == "array":
                        item_type = param_schema.get("items", dict()).get("type", "string")
                        if not have_enum:
                            headers[param_name] = f"[{param_name}]" if self.get_label_name(
                                param_name) else f"<[random-{item_type}]>"
                        else:
                            headers[param_name] = random.choice(enum_array)

                    elif param_type == "object":
                        properties = param_schema.get("properties", dict())
                        headers[param_name] = {
                            key: (f"{self.get_label_name(key)}" if self.get_label_name(
                                key) else f"<random-{val.get('type', 'string')}>")
                            for key, val in properties.items()
                        }

                    elif param_type == "integer":
                        headers[param_name] = random.randint(0, 9999999)

                    elif param_type == "number":
                        headers[param_name] = random.uniform(0, 9999999)

                    else:
                        if not have_enum:
                            headers[param_name] = f"{self.get_label_name(param_name)}" if self.get_label_name(
                                param_name) else f"<random-{param_type}>"
                        else:
                            headers[param_name] = random.choice(enum_array)

                elif param.get("in") == "body" :
                    if have_enum:
                        req_body[param_name] = random.choice(param_schema["enum"])
                    else:
                        req_body[param_name] = self.generate_body_from_schema(param_schema)

                elif param.get("in") == "formData" :
                    if have_enum:
                        form_data[param_name] = random.choice(param_schema["enum"])
                    else:
                        form_data[param_name] = "<random-string>"

                if req_body:
                    for key, val in form_data.items():
                        req_body[key] = val

                elif form_data:
                    req_body['Body'] = form_data

        return f"?{'&'.join(query_params)}" if query_params else "", headers, req_body

    def extract_response(self, response, version, content_type="application/json"):
        response_body = {}

        if version == "2":
            schema = response.get("schema", dict())

            response_body = self.generate_body_from_schema(schema)

        elif version == "3":
            content = response.get("content", dict())

            if content_type not in content.keys():
                content_type = "application/json"

            for cnt_type, schema_info in content.items():
                if cnt_type == content_type:
                    schema = schema_info.get("schema", dict())
                    response_body = self.generate_body_from_schema(schema)
                    break

        return response_body if response_body else dict()

    def get_label_name(self, label_name):
        for label, regex in self.label_regex.items():
            for reg in regex:
                if re.search(reg, label_name):
                    return label
        return ""

    def oas_ver_3(self):
        for url in self.specs.get("servers", []) :
            inp_url = re.sub(r"https?://", "", url["url"])
            inp_host, base_path = (
                inp_url.split("/", 1) if "/" in inp_url else (inp_url, ""))
            base_path = "/" + base_path

        inp_host = ("Default" if not inp_host else inp_host)

        api_count = 1
        row, column = 0, 0
        head_format = self.workbook.add_format({ "bold" : True, "bottom" : 2, "bg_color" : "#0B6623" })

        for head in HEADER_LIST :
            self.worksheet.write(row, column, head, head_format)
            column += 1
        row += 1

        content_type_not_found = False

        for api, api_info in self.specs["paths"].items() :
            new_api = True
            updated_api = self.extract_path_params(api, api_info)

            for method, method_info in api_info.items() :
                if method == "parameters":
                    continue

                query_param, headers, request_body = self.extract_params(method_info)
                inp_url = (base_path if base_path!='/' else "") + updated_api + query_param

                request_body = method_info.get("requestBody", dict())

                if request_body == { } or request_body["content"] == { } :
                    request_body = { "content" : { "application/json" : { "schema" : { } } } }

                for content_type, _ in request_body["content"].items() :
                    if content_type not in CONTENT_TYPE_LIST :
                        content_type_not_found = True
                        continue

                    if "json" in content_type or content_type == "*/*" or content_type == "text/plain" :
                        content_type = "application/json"

                    content_type_not_found = False

                    req_body = self.extract_request_body(request_body, content_type)
                    if content_type == "application/xml" :
                        req_body = { "Body" : req_body }

                    req_body = json.dumps(req_body)

                    for rspcode in method_info["responses"].keys() :
                        # resp_body = self.extract_response(method_info["responses"].get(rspcode, dict()), "3", content_type)           // Don't Need it for Traffic Generation.

                        headers["Content-Type"] = content_type
                        headers["apisec-resp-payload"] = { }
                        headers["apisec-resp-status-code"] = ("200" if rspcode == "default" else rspcode)
                        resp_body = { "no-resp-body" : True }

                        org_header = json.dumps(headers)
                        resp_body = json.dumps(resp_body)

                        row_vals = [inp_url, inp_host, method.upper(), ("200" if rspcode == "default" else rspcode),
                                    org_header, req_body, resp_body]
                        column = 1

                        for value in row_vals :
                            self.worksheet.write(row, column, value)
                            if new_api :
                                self.worksheet.write(row, 0, api_count)
                                new_api = False
                            column += 1
                        row += 1

                    if '?' in inp_url :
                        inp_url = inp_url.split('?')[0] + '/UnknownPath?' + inp_url.split('?')[1]
                    else :
                        inp_url = inp_url + '/UnknownPath'

                    invalid_vals = [inp_url, inp_host, method.upper(), "403", str(org_header), str(request_body), str(resp_body)]
                    column = 1
                    for value in invalid_vals :
                        self.worksheet.write(row, column, value)
                        column += 1
                    row += 1

            if content_type_not_found :
                content_type_not_found = False
                continue

            api_count += 1
            row += 1

        self.workbook.close()
        return base_path

    def oas_ver_2(self):
        base_path = self.specs.get("basePath", "/")
        inp_host = self.specs.get("host", "Default")

        api_count = 1
        row, column = 0, 0
        head_format = self.workbook.add_format({ "bold" : True, "bottom" : 2, "bg_color" : "#0B6623" })

        for head in HEADER_LIST :
            self.worksheet.write(row, column, head, head_format)
            column += 1
        row += 1

        content_type_not_found = False

        for api, api_info in self.specs["paths"].items() :
            new_api = True
            updated_api = self.extract_path_params(api, api_info)

            for method, method_info in api_info.items() :
                if method == "parameters":
                    continue

                query_param, headers, request_body = self.extract_params(method_info)
                inp_url = (base_path if base_path!='/' else "") + updated_api + query_param

                required_body = request_body.copy()

                for name, value in request_body.items() :
                    required_body = value
                    break

                request_body = json.dumps(required_body)

                content_types = []

                if "consumes" in method_info.keys() :
                    for content in method_info["consumes"]:
                        content_types.append(content)

                elif "consumes" in self.specs.keys() :
                    for content in self.specs["consumes"]:
                        content_types.append(content)

                elif "produces" in method_info.keys() :
                    for content in method_info["produces"]:
                        content_types.append(content)

                elif "produces" in self.specs.keys() :
                    for content in self.specs["produces"]:
                        content_types.append(content)

                else:
                    content_types.append("application/json")

                if len(content_types) == 0:
                    content_types.append('application/json')


                for content_type in content_types :

                    if content_type not in CONTENT_TYPE_LIST :
                        content_type_not_found = True
                        continue

                    if "json" in content_type or content_type == "*/*" or content_type == "text/plain" :
                        content_type = "application/json"

                    content_type_not_found = False

                    for rspcode in method_info["responses"].keys() :

                        # resp_body = self.extract_response(method_info["responses"].get(rspcode, dict()), "2")

                        headers["Content-Type"] = content_type
                        headers["apisec-resp-payload"] = { }
                        headers["apisec-resp-status-code"] = ("200" if rspcode == "default" else rspcode)
                        resp_body = { "no-resp-body" : True }

                        org_header = json.dumps(headers)
                        resp_body = json.dumps(resp_body)

                        row_vals = [inp_url, inp_host , method.upper(), ("200" if rspcode == "default" else rspcode),
                                    org_header, request_body, resp_body]
                        column = 1

                        for value in row_vals :
                            self.worksheet.write(row, column, value)
                            if new_api :
                                self.worksheet.write(row, 0, api_count)
                                new_api = False
                            column += 1
                        row += 1

                    if '?' in inp_url :
                        inp_url = inp_url.split('?')[0] + '/UnknownPath?' + inp_url.split('?')[1]
                    else:
                        inp_url = inp_url + '/UnknownPath'

                    invalid_vals = [inp_url, inp_host, method.upper(), "403", org_header, request_body, resp_body]
                    column = 1
                    for value in invalid_vals :
                        self.worksheet.write(row, column, value)
                        column += 1
                    row += 1

            if content_type_not_found :
                content_type_not_found = False
                continue

            api_count += 1
            row += 1

        self.workbook.close()
        return base_path

    def run_main(self):
        self.specs, version = Resolver(self.swagger_file).input_scan()

        fun_call = f"oas_ver_{version}"

        base_pth = getattr(self, fun_call)()

        return base_pth


if __name__ == "__main__":
    swagger_file = "/Users/peddireddymsailalith.aditya/api-security-automation/lib/SpecTrafficGenerator/spec_testing/account-1361974-api-files/55558081-api.bankmandiri.co.id-api-1213-_rad_AutoSwaggerOpenAPI_accountInfoExternalRestDesc.yaml"
    base_path = OpenApiSpecParser(swagger_file).run_main()

    xlparser = XlSXParser(f"./OutputFiles/{swagger_file.split('/')[-1]}.xlsx", "discovery_engine")
    xlparser.get_json_file(f"./OutputFiles/{swagger_file.split('/')[-1]}.json")
