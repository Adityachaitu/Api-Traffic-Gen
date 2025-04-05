import os
import sys
import time
import traceback

import yaml
import json

from concurrent.futures import ThreadPoolExecutor

from lib.SpecTrafficGenerator.OpenApiSpecParser import OpenApiSpecParser
from lib.api.client_stubs.apisecurity.current.rest import ApiException
from lib.parsers.xlsx_parser import XlSXParser
from lib.trafficgenerator.traffic_generator import TrafficGenerator
from lib.api.apiobjects.inventory.myapi.api_inventory import ApiInventory
from lib.api.imperva_api import ImpervaAPI
from lib.loggers.logger import report_logger

logger = report_logger()

RESPONSE_DELAY = 30
TEST_ENV = "<confidential>"
USE_RECEIVER = "False"
HOST = "<your Host>"
SITE_IDS = [<List of Site Ids Used>]
ON_BOARDED_SITES = {
    SITE_IDS[0] : "<Host or site name>"
}
ACC_ID = ********
API_KEY = "<API_KEY>"
API_ID = <API_KEY>

def send_valid_traffic(outputfile, host):
    logger.info("Send Traffic")
    traffic_gen_obj = TrafficGenerator(TEST_ENV, USE_RECEIVER, host = host)

    with open(outputfile, "r") as out_file :
        data = json.load(out_file)

    for test_id, testcase in data.items() :
        traffic_gen_obj.send_traffic(testcase["input"], str(test_id), num_threads=0)


class OpenApiSpecTest(object):
    def __init__(self, **kwargs):
        self.api = ImpervaAPI(feature="open_api_spec_test", host=kwargs["host"],
                              account_id=kwargs["account_id"], api_key=kwargs["api_key"], api_id=kwargs["api_id"])

        self.inventory_api = ApiInventory(api_obj=self.api)

    def upload_swagger_file(self, basepath='/', swaggerfile=None, api_specification=None, description="Adding Swagger file.", specification_violation_action='BLOCK_REQUEST',
                            violation_action=None, validate_host=False, site_id=None):

        api_file_id = self.inventory_api.add_oas_file(base_path=basepath,
                                                 oas_file_name=swaggerfile,
                                                 api_specification=api_specification,
                                                 description=description,
                                                 specification_violation_action=specification_violation_action,
                                                 violation_actions=violation_action,
                                                 validate_host=validate_host,
                                                 site_id=site_id)

        return api_file_id

    def set_block_upload(self, swagger_file, api_specification, site_id, specification_violation_action='BLOCK_REQUEST', base_path='/'):

        violation_actions = { "invalid_url_violation_action" : "DEFAULT",
                              "invalid_method_violation_action" : "DEFAULT",
                              "invalid_param_name_violation_action" : "DEFAULT",
                              "missing_param_violation_action" : "DEFAULT",
                              "invalid_param_value_violation_action" : "DEFAULT",
                              "other_traffic_violation_action" : "DEFAULT" }

        return self.upload_swagger_file(basepath=base_path, swaggerfile=swagger_file, api_specification=api_specification,
                                        specification_violation_action=specification_violation_action, violation_action= json.dumps(violation_actions), site_id=site_id)

    def delete_swagger_file(self, api_file_id, site_id):
        return self.inventory_api.delete_oas_file(api_file_id=api_file_id, site_id=site_id)


def get_files(folder):
    file_lst = []

    for item in os.listdir(folder):
        if item.endswith(".json") or item.endswith(".yaml") or item.endswith(".yml"):
            if ':' in item:
                item_renamed = item.replace(':', '_')
                os.rename(os.path.join(folder, item), os.path.join(folder, item_renamed))
                item = item_renamed
            file_lst.append(item)

    return file_lst

def process_file(file, index, directory_name, oas_test, files_tested, files_yet_to_be_tested_manually, unsuccessful_deletes):

    file_id = None
    site_id = SITE_IDS[index%len(SITE_IDS)]
    host = ON_BOARDED_SITES[site_id]

    try:
        swagger_file = os.path.join(directory_name, file)
        base_path = OpenApiSpecParser(swagger_file).run_main()

        logger.info(f"base_path: {base_path}")

        file_id = oas_test.set_block_upload(base_path=base_path, swagger_file=file,
                                            api_specification=swagger_file, site_id=site_id)

        logger.info(f"file_id: {file_id} uploaded successfully.")

        xlparser = XlSXParser(f"./OutputFiles/{swagger_file.split('/')[-1]}.xlsx", "discovery_engine")
        xlparser.get_json_file(f"./OutputFiles/{file}.json")

        logger.info("Created the Output.json file.")

        logger.info(f"waiting for {RESPONSE_DELAY} seconds to publish the policies")
        time.sleep(RESPONSE_DELAY)

        send_valid_traffic(f"./OutputFiles/{file}.json", host=host)

        files_tested.append({
            "file_id": file_id,
            "file": file,
            "host": host
        })

        deleted_oas = oas_test.delete_swagger_file(api_file_id=file_id, site_id=site_id)

        if not deleted_oas :
            unsuccessful_deletes.append({
                "file_id" : file_id,
                "file" : file,
                "host" : host
            })

        logger.info(f"Tested {file} file Correctly.")

    except Exception as e:
        tb = sys.exc_info()
        logger.error(f"\n\n\nEXCEPTION AT LINE : {tb[2].tb_lineno}: {e}")

        files_yet_to_be_tested_manually.append({
                "file_id" : file_id,
                "file": file,
                "host" : host,
                "Exception Line": tb[2].tb_lineno,
                "Exception Class": tb[0].__name__,
                "Exception Value": str(tb[1]),
                "Traceback": "".join(traceback.format_tb(tb[2]))
            })

        logger.info(f"\n\n\n {file} is yet to be published\n\n\n")

    finally:
        if index != len(file_list)-1 :
            logger.info(f"Waiting for 10 minutes for testing a new file.")
            time.sleep(600)

if __name__ == "__main__" :

    directory_name = "./<swagger file Location>"

    file_list = get_files(directory_name)

    files_yet_to_be_tested_manually = []
    files_tested = []
    unsuccessful_deletes = []

    oas_test = OpenApiSpecTest(host=HOST, account_id=ACC_ID, api_key=API_KEY, api_id=API_ID)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []

        for index, file in enumerate(file_list):
            futures.append(executor.submit(process_file, file, index, directory_name, oas_test, files_tested, files_yet_to_be_tested_manually, unsuccessful_deletes))

        for future in futures:
            future.result()

    logger.info(f"Tested {len(files_tested)}/{len(file_list)} files correctly in total")

    json_obj = {
        "Executed" : files_tested,
        "Not Executed" : files_yet_to_be_tested_manually,
        "Not Deleted" : unsuccessful_deletes
    }

    with open(f"Execution_Data_{directory_name.split('/')[-1]}.json", "w") as j_file:
        json.dump(json_obj, j_file, indent=4)
