import xml.dom.minidom
from typing import List, Dict


# will be nvidia-smi -q  -x 's output is parsed as visual data
def parse_gpus(gpu_str: str) -> List[Dict]:
    dom_tree = xml.dom.minidom.parseString(gpu_str)
    collections = dom_tree.documentElement
    gpus = collections.getElementsByTagName('gpu')
    res = []
    for one in gpus:
        fb_mem_elem = one.getElementsByTagName('fb_memory_usage')[0]
        gpu_uuid_elem = one.getElementsByTagName('uuid')[0]
        gpu_id_elem = one.getElementsByTagName('minor_number')[0]
        gpu_total_mem = fb_mem_elem.getElementsByTagName('total')[0]
        free_mem = fb_mem_elem.getElementsByTagName('free')[0]
        gpu_utility_elem = one.getElementsByTagName('utilization')[0].getElementsByTagName(
            'gpu_util')[0]
        res.append({
            'gpu_uuid':
                gpu_uuid_elem.firstChild.data,
            'gpu_id':
                gpu_id_elem.firstChild.data,
            'gpu_total_mem':
                '%.2f G' % (float(gpu_total_mem.firstChild.data.split(' ')[0]) / 1024),
            'gpu_used_mem':
                '%.2f G' % (float(free_mem.firstChild.data.split(' ')[0]) / 1024),
            'gpu_utility':
                round(float(gpu_utility_elem.firstChild.data.split(' ')[0]) / 100, 2)
        })
    return res


def parse_server_host(endpoint: str):
    """ Put the data in the databaseendpointsResolve tohttpRequestedhost """
    endpoint = endpoint.replace('http://', '').split('/')[0]
    return f'http://{endpoint}'
