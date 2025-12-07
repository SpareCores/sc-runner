# Spare Cores Runner

Spare Cores Runner is a command-line tool and Python API designed to simplify the process of provisioning
and managing cloud instances across various cloud providers.
It leverages Pulumi to handle infrastructure-as-code and automate the creation and destruction of
compute instances in your preferred cloud environment.

Spare Cores Runner (`sc-runner` from now on) is used by [Spare Cores Inspector](https://github.com/SpareCores/sc-inspector)
to start up basic cloud instances with the required minimum configuration and environment to start the machine with a custom
`cloud-init` script, but it can also be used to simply start an instance with a given SSH key, making it available for basic
use cases.

## Supported Cloud Providers and their Credentials

`sc-runner` uses the Spare Cores database to pre-fill the available configuration options, like what regions and instance
types are available for a given cloud provider.
To use a given cloud provider, you have to provide credentials for them, either by running it in an environment
where the underlying library can pick them up, or by specifying them through environment variables or command line options.

For more details, see the supported vendor's Pulumi integration:

* [AWS](https://www.pulumi.com/registry/packages/aws/installation-configuration/)
* [Azure](https://www.pulumi.com/registry/packages/azure-native/installation-configuration/)
* [GCP](https://www.pulumi.com/registry/packages/gcp/installation-configuration/), [GOOGLE_CREDENTIALS](https://www.pulumi.com/registry/packages/gcp/service-account/)
* [Hetzner Cloud](https://www.pulumi.com/registry/packages/hcloud/)
* [UpCloud](https://github.com/UpCloudLtd/pulumi-upcloud)
* [OVHcloud](https://www.pulumi.com/registry/packages/ovh/)

## Pulumi

As `sc-runner` uses Pulumi under the hood to manage the cloud providers, it'll need to have a Pulumi project.
You can configure Pulumi project-related settings either by specifying them using command line arguments, shown below:

```shell
sc-runner create --help
Usage: sc-runner create [OPTIONS] COMMAND [ARGS]...

Options:
  --project-name TEXT        Pulumi project name  [default: runner]
  --work-dir TEXT            Pulumi work dir  [default: /data/workdir]
  --pulumi-home TEXT         Pulumi home  [default: /root/.pulumi]
  --pulumi-backend-url TEXT  Pulumi backend URL  [default: file:///data/backend]
  --stack-name TEXT          Pulumi stack name, defaults to
                             {vendor}.{region}.{zone}.{instance_id} or similar
  --help                     Show this message and exit.

Commands:
  aws
  azure
  gcp
  hcloud
  ovh
  upcloud
```

Or by setting the following environment variables:

* PULUMI_PROJECT_NAME
* PULUMI_WORK_DIR
* PULUMI_HOME
* PULUMI_BACKEND_URL

`sc-runner` should create the project on the first invocation, during which it'll create multiple stacks for each
`vendor.region.zone.instance_id` tuple. This allows concurrent creation of instances, supporting our
Spare Cores Inspector use case, where we start a given instance type once to collect data from them.

## Usage
### CLI examples

#### Create instances

Create and destroy a default `t3.micro` instance in the default VPC/subnet in AWS:
```shell
sc-runner create aws
sc-runner destroy aws
```

Create an Azure instance with a public key:
```shell
sc-runner create azure --instance Standard_DS1_v2 --public-key $(cat .ssh/id_ed25519.pub)
```

Create an AWS instance with public IP and an already stored SSH key named `spare_cores`:
```shell
sc-runner create aws --region us-west-2 --instance t4g.large --instance-opts '{"associate_public_ip_address": true,"key_name":"spare-cores"}' --public-key ""
```

#### Destroy instances

```shell
sc-runner destroy azure --instance Standard_DS1_v2
sc-runner destroy aws --region us-west-2 --instance t4g.large
```

You can also use `destroy-stack` instead of `destroy`, which performs a `pulumi refresh` first, synchronizing the underlying
cloud state with Pulumi's internal backend and destroying only what's really there (so it won't fail on already deleted
resources).

##### Cancelling Pulumi Locks

Sometimes Pulumi might leave a lock file in its state store, preventing further operations. With this command you can
cancel those:

```shell
sc-runner cancel aws --region us-west-2 --instance t4g.large
```

### Docker

`sc-runner` is available through a Docker image as well, which you can use with the following command:
```shell
docker run --rm -ti ghcr.io/sparecores/sc-runner:main --help
```

You'll have to set up the same environment variables or configure the cloud credentials for Pulumi.
