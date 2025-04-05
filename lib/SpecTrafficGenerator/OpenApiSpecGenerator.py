from prance import ResolvingParser
from prance.util.resolver import default_reclimit_handler
from openapi_spec_validator.shortcuts import validate
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError
from lib.loggers.logger import report_logger

logger = report_logger()

def fix_response_codes(spec):
    if "paths" not in spec:
        return
    for path, methods in spec["paths"].items():
        for method, details in methods.items():
            if "responses" in details:
                responses = details["responses"]
                for code in list(responses.keys()):
                    if isinstance(code, int):
                        responses[str(code)] = responses.pop(code)

# Custom recursion handler
def custom_reclimit_handler(limit, ref_url, recursions):
    if len(recursions) > 1:
        return {}
    return default_reclimit_handler(1,ref_url, recursions)

# Custom Response Code Integer Value handler
def custom_validate_openapi_spec_validator(self, validator):
    try:
        fix_response_codes(self.specification)  # Fix response codes before validation
        validate(self.specification)  # Run OpenAPI validation
    except OpenAPIValidationError as e:
        print(f"Validation Error: {e}")
        print("Continuing with fixed spec...")

import prance.util.resolver
prance.util.resolver.default_reclimit_handler = custom_reclimit_handler
ResolvingParser._validate_openapi_spec_validator = custom_validate_openapi_spec_validator


class Resolver(object):
    def __init__(self, spec_path):
        self.spec_path = spec_path
        self.spec = ResolvingParser(spec_path, backend='openapi-spec-validator').specification
    
    def input_scan(self):
        version = "3"

        self._process_parameters_under_path()

        if "swagger" in self.spec.keys() or "basePath" in self.spec.keys() or "host" in self.spec.keys():
            version = "2"
            if 'securityDefinitions' in self.spec.keys():
                self._process_security_definitions(self.spec['securityDefinitions'])

            self.spec.pop('definitions', None)
            self.spec.pop('parameters', None)
        else:
            if 'components' in self.spec.keys() and 'securitySchemes' in self.spec['components'].keys():
                self._process_security_definitions(self.spec['components']['securitySchemes'])
            self.spec.pop('components', None)

        return self.spec, version

        # for api, apiInfo in self.spec['paths'].items():
        #     for method, methodInfo in apiInfo.items():
        #         newParameters = methodInfo.get('parameters', [])
        #         if 'requestBody' in methodInfo:
        #             newParameters += self._process_request_body(methodInfo['requestBody'])
        #             self.spec['paths'][api][method]['parameters'] = newParameters
        # return self.spec, version

    def _process_security_definitions(self, security_definitions):
        extra_params = []
        for api_head_name, values in security_definitions.items():
            if values['type'] == 'apiKey':
                extra_params.append({ 'in' : values['in'], 'type' : 'string', 'name' : values['name'] })
            elif values['type'] == 'http' and values['scheme'] == 'bearer':
                extra_params.append({'in' : 'header', 'type' : 'string', 'name' : 'Authorization' })

        for _, method_in in self.spec['paths'].items():
            for method, method_info in method_in.items():
                if method == 'parameters':
                    continue

                if 'parameters' in method_info.keys():
                    for param in extra_params:
                        method_info['parameters'].append(param)
                else:
                    method_info['parameters'] = extra_params

    def _process_parameters_under_path(self):
        extra_under_path_params = []
        for path, path_info in self.spec['paths'].items():
            if 'parameters' in path_info.keys():
                for param in path_info['parameters']:
                    extra_under_path_params.append(param)

        if extra_under_path_params:
            for _, path_info in self.spec['paths'].items():
                for method, method_info in path_info.items():
                    if method == 'parameters':
                        continue

                    if 'parameters' in method_info.keys():
                        for param in extra_under_path_params:
                            method_info['parameters'].append(param)
                    else:
                        method_info['parameters'] = extra_under_path_params

    def _process_request_body(self, request_body):
        params = []
        for header, body in request_body.get('content').items():
            payload = self._process_objects(body['schema'], None)
            if type(payload) == dict:
                for param, paramInfo in payload.items():
                    params.append({'in': 'body', 'name': param, 'value': paramInfo, 'required': True if param in list(body['schema']['required'] if 'required' in body['schema'].keys() else list()) else False})
        return params
    
    def _process_objects(self, body, last_key, payload={}):
        type = body.get('type')
        if type == 'object':
            if last_key:
                payload[last_key] = None
            data = {}
            for key, info in body.get('properties').items():
                data[key] = self._process_objects(info, key)
                payload = data
        elif type == 'array':
            payload = []
            data = self._process_objects(body.get('items'), None)
            payload.append(data)
        else:
            return body.get('example', '')
        return {'unknownVariable': payload} if last_key == None and type != 'object' else payload
