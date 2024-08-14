import requests

# Define metadata service endpoints for each cloud provider
CLOUD_METADATA_ENDPOINTS = {
    "aws": "http://169.254.169.254/latest/meta-data/instance-id",
    "azure": "http://169.254.169.254/metadata/instance/compute/vmId?api-version=2021-02-01",
    "gcp": "http://metadata.google.internal/computeMetadata/v1/instance/id",
    "alibaba": "http://100.100.100.200/latest/meta-data/instance-id",
    "digitalocean": "http://169.254.169.254/metadata/v1/id",
    "oracle": "http://169.254.169.254/opc/v1/instance/id",
    "openstack": "http://169.254.169.254/openstack/latest/meta_data.json",
}

# Headers required for specific cloud providers
CLOUD_METADATA_HEADERS = {
    "gcp": {"Metadata-Flavor": "Google"},
    "azure": {"Metadata": "true"},
}


def check_endpoint(url, headers=None):
    try:
        response = requests.get(url, headers=headers, timeout=1)
        if response.status_code == 200:
            return response
    except requests.exceptions.RequestException:
        pass
    return None

def get_instance_id():
    for cloud, url in CLOUD_METADATA_ENDPOINTS.items():
        headers = CLOUD_METADATA_HEADERS.get(cloud, {})
        response = check_endpoint(url, headers)
        if response:
            if cloud == "openstack":
                # OpenStack returns JSON, extract instance ID accordingly
                data = response.json()
                return data.get("uuid"), "openstack"
            else:
                return response.text.strip(), cloud
    return None, None

if __name__ == "__main__":
    instance_id, cloud_provider = get_instance_id()
    if instance_id:
        print(f"Cloud Provider: {cloud_provider.upper()}")
        print(f"Instance ID: {instance_id}")
    else:
        print("Could not determine the cloud environment or fetch the instance ID.")
