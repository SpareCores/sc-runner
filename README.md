# sc-runner
Spare Cores Runner

## Usage
### CLI

Create and destroy a default `t3.micro` instance in the default VPC/subnet in AWS:
```shell
sc-runner create aws
sc-runner destroy aws
```

### Docker
```shell
docker run --rm -ti ghcr.io/sparecores/sc-runner:main --help
```