"""
Copyright 2021 Adobe
All Rights Reserved.

NOTICE: Adobe permits you to use, modify, and distribute this file in accordance
with the terms of the Adobe license agreement accompanying it.
"""

import base64
import os.path
import socket
import ssl
from collections import OrderedDict
from os import listdir
from os.path import isfile, join, getmtime
from types import GeneratorType

import docker.errors
import six
from docker.utils import compare_version

from buildrunner.docker import (
    new_client,
    force_remove_container,
    BuildRunnerContainerError,
)
from buildrunner.utils import tempfile


class DockerRunner:
    """
    An object that manages and orchestrates the lifecycle and execution of a
    Docker container.
    """

    class ImageConfig:
        """
        An object that captures image-specific configuration
        """
        def __init__(self, image_name, pull_image=True, platform=None):
            self.image_name = image_name
            self.pull_image = pull_image
            self.platform = platform

    def __init__(self, image_config, dockerd_url=None, log=None):
        image_name = image_config.image_name
        pull_image = image_config.pull_image
        platform = image_config.platform

        self.image_name = image_name.lower()
        self.platform = platform
        if log and self.image_name != image_name:
            log.write(f'Forcing image_name to lowercase: {image_name} => {self.image_name}\n')
        self.docker_client = new_client(
            dockerd_url=dockerd_url,
            # Disable timeouts for running commands
            timeout=0,
        )
        self.container = None
        self.shell = None
        self.committed_image = None
        self.containers = []

        # By default, pull the image.  If the pull_image parameter is
        # set to False, only pull the image if it can't be found locally
        #
        # Pull all images to ensure we get the hashes for intermediate images
        found_image = False
        for image in self.docker_client.images(all=True):
            if image["Id"].startswith("sha256:" + self.image_name) or image["Id"] == self.image_name:
                # If the image name is simply a hash, it refers to an intermediate
                # or imported image.  We don't want to "pull" these, as the hash
                # won't exist as a valid upstream repoistory/image
                found_image = True
                pull_image = False
            else:
                for tag in image['RepoTags'] or []:
                    if tag == self.image_name:
                        found_image = True
                        break
            if found_image:
                # No need to continue once we've found the image
                break

        if pull_image or not found_image:
            if log:
                log.write(f'Pulling image {self.image_name}\n')
            for data in self.docker_client.pull(self.image_name, stream=True, decode=True, platform=self.platform):
                # Unused variable (see comment below about interactive mode)
                _ = data
                if log:
                    log.write('.')
                    # If we implement an interactive mode, this could be used instead
                    # line = data.get('progress', data.get('status')) or '...'
                    # log.write(f'\r{line:<80}')
            if log:
                log.write('\nImage pulled successfully\n')

    def start(
            self,
            shell='/bin/sh',
            working_dir=None,
            name=None,
            volumes=None,
            volumes_from=None,
            links=None,
            ports=None,
            provisioners=None,
            environment=None,
            user=None,
            hostname=None,
            dns=None,
            dns_search=None,
            extra_hosts=None,
            containers=None,
            systemd=None,
            cap_add=None,
            privileged=False,
    ):  # pylint: disable=too-many-arguments,too-many-locals
        """
        Kwargs:
          volumes (dict): mount the local dir (key) to the given container
                          path (value)
        """
        if self.container:
            raise BuildRunnerContainerError('Container already started')
        self.shell = shell

        # save any spawned containers
        if containers:
            self.containers = containers

        # prepare volumes
        _volumes = []
        _binds = {}

        security_opt = None
        command = shell
        if systemd:
            # If we are running in a systemd context,
            # the following 3 settings are necessary to
            # allow services to run.
            volumes["/sys/fs/cgroup"] = "/sys/fs/cgroup:ro"
            security_opt = ["seccomp=unconfined"]
            command = "/usr/sbin/init"

        if volumes:
            for key, value in volumes.items():
                to_bind = value
                _ro = False
                if to_bind.rfind(':') > 0:
                    tokens = to_bind.rsplit(':', 1)
                    to_bind = tokens[0]
                    _ro = tokens[1] == 'ro'
                _volumes.append(to_bind)
                _binds[key] = {
                    'bind': to_bind,
                    'ro': _ro,
                }

        # prepare ports
        _port_list = None
        if ports:
            _port_list = list(ports.keys())

        # check args
        if dns_search and isinstance(dns_search, six.string_types):
            dns_search = dns_search.split(',')

        kwargs = {
            'name': name,
            'command': command,
            'volumes': _volumes,
            'ports': _port_list,
            'stdin_open': True,
            'tty': True,
            'environment': environment,
            'user': user,
            'working_dir': working_dir,
            'hostname': hostname,
            'host_config': self.docker_client.create_host_config(
                binds=_binds,
                links=links,
                port_bindings=ports,
                volumes_from=volumes_from,
                dns=dns,
                dns_search=dns_search,
                extra_hosts=extra_hosts,
                security_opt=security_opt,
                cap_add=cap_add,
                privileged=privileged
            )
        }

        if compare_version('1.10', self.docker_client.api_version) < 0:
            kwargs['dns'] = dns

        # start the container
        self.container = self.docker_client.create_container(self.image_name, **kwargs)
        self.docker_client.start(self.container['Id'])

        # run any supplied provisioners
        if provisioners:
            for provisioner in provisioners:
                try:
                    provisioner.provision(self)
                except Exception as ex:
                    self.cleanup()
                    raise ex

        return self.container['Id']

    def stop(self):
        """
        Stop the backing Docker container.
        """
        if self.container:
            self.docker_client.stop(
                self.container['Id'],
                timeout=0,
            )

    def cleanup(self):
        """
        Cleanup the backing Docker container, stopping it if necessary.
        """
        if self.container:
            for container in self.containers:
                try:
                    force_remove_container(self.docker_client, container)
                except docker.errors.NotFound:
                    try:
                        container_ids = self.docker_client.containers(
                            filters={'label': container},
                            quiet=True
                        )
                        if container_ids:
                            for container_id in container_ids:
                                self.docker_client.remove_container(
                                    container_id['Id'],
                                    force=True,
                                    v=True,
                                )
                        else:
                            print(f'Unable to find docker container with name or label "{container}"')
                    except docker.errors.NotFound:
                        print(f'Unable to find docker container with name or label "{container}"')

            self.docker_client.remove_container(
                self.container['Id'],
                force=True,
                v=True,
            )

        self.container = None

    def restore_caches(self, caches: OrderedDict, cache_archive_ext: str):  # pylint: disable=too-many-branches,too-many-locals
        """
        Restores caches from the host system to the destination location in the docker container.
        """
        if caches is None or not isinstance(caches, OrderedDict):
            raise TypeError(f"Caches should be of type OrderedDict instead caches are type {type(caches)}")

        restored_cache_src = set()
        for local_cache_archive_file, docker_path in caches.items():
            if docker_path in restored_cache_src:
                print(f"Destination path {docker_path} has already been matched and restored to the container "
                      f"skipping {local_cache_archive_file} -> {docker_path}")
                continue

            # Check for prefix matching
            if not os.path.exists(local_cache_archive_file):
                cache_dir = os.path.dirname(local_cache_archive_file)

                if not os.path.exists(cache_dir):
                    print(f"Cache directory {cache_dir} does not exist, "
                          f"skipping restore of archive {local_cache_archive_file}")
                    continue

                files = [f for f in listdir(cache_dir) if isfile(join(cache_dir, f))]

                cache_key = local_cache_archive_file\
                    .replace(f"{cache_dir}/", "")\
                    .replace(f".{cache_archive_ext}", "")

                most_recent_time = 0
                local_cache_archive_match = None
                for file in files:
                    if file.startswith(cache_key):
                        print(f"    starts with {cache_key}")
                        curr_archive_file = join(cache_dir, file)
                        mod_time = getmtime(curr_archive_file)
                        if mod_time > most_recent_time:
                            most_recent_time = mod_time
                            local_cache_archive_match = curr_archive_file

                if local_cache_archive_match is None:
                    print(f"WARNING: Not able to restore cache {docker_path} since "
                          f"there was no prefix matching for [{local_cache_archive_file}]")
                    continue

                local_cache_archive_file = local_cache_archive_match

            orig_shell = self.shell
            try:
                self.shell = "/bin/sh"
                exit_code = self.run(f"mkdir -p {docker_path}")
                if exit_code:
                    print(f"WARNING: There was an issue creating {docker_path} on the docker container.")

                with open(local_cache_archive_file, 'rb') as data:
                    print(f"{local_cache_archive_file}:{docker_path}")

                    restored_cache_src.add(docker_path)
                    if not self.docker_client.put_archive(self.container['Id'], docker_path, data):
                        print(f"WARNING: An error occurred when trying to use cache "
                              f"{local_cache_archive_file}:{docker_path}")

            except docker.errors.APIError as exception:
                print(f"WARNING: An docker.errors.APIError has occurred\n{exception}")
            finally:
                self.shell = orig_shell

    def save_caches(self, caches: OrderedDict):
        """
        Saves caches from a source locations in the docker container to locations on the host system as archive file.
        """
        saved_cache_src = set()
        if caches and isinstance(caches, OrderedDict):
            for local_cache_archive_file, docker_path in caches.items():
                if docker_path not in saved_cache_src:
                    saved_cache_src.add(docker_path)
                    print(f"Saving cache [{docker_path}] "
                          f"running on container {self.container['Id']} "
                          f"to local cache [{local_cache_archive_file}]")

                    # with open(local_cache_archive_file, 'wb') as file:
                    #     bits, _ = self.docker_client.get_archive(self.container['Id'], f"{docker_path}/.")
                    #     for chunk in bits:
                    #         file.write(chunk)
                else:
                    print(f"The following {docker_path} in docker has already been saved. "
                          f"It will not be save again to {local_cache_archive_file}")

    # pylint: disable=too-many-branches,too-many-arguments
    def run(self, cmd, console=None, stream=True, log=None, workdir=None):
        """
        Run the given command in the container.
        """
        # Unused variable
        _ = workdir

        if isinstance(cmd, str):
            cmdv = [self.shell, '-xc', cmd]
        elif hasattr(cmd, 'next') or hasattr(cmd, '__next__') or hasattr(cmd, '__iter__') or \
                isinstance(cmd, GeneratorType):
            cmdv = cmd
        else:
            raise TypeError(f'Unhandled command type: {type(cmd)}:{cmd}')
        # if console is None:
        #    raise Exception('No console!')
        if not self.container:
            raise BuildRunnerContainerError('Container has not been started')
        if not self.shell:
            raise BuildRunnerContainerError(
                'Cannot call run if container cmd not shell'
            )

        if log:
            log.write(f'Executing: {cmdv}\n')

        create_res = self.docker_client.exec_create(
            self.container['Id'],
            cmdv,
            tty=False,
            # workdir=workdir,
        )
        output_buffer = self.docker_client.exec_start(
            create_res,
            stream=stream,
        )
        if isinstance(output_buffer, (bytes, str)):
            if console:
                console.write(output_buffer)
            if log:
                log.write(output_buffer)
        elif hasattr(output_buffer, 'next') or isinstance(output_buffer, GeneratorType):
            try:
                for line in output_buffer:
                    if console:
                        console.write(line)
                    if log:
                        log.write(line)
            except socket.timeout:
                # Ignore timeouts since we check for the exit code anyways at the end
                pass
        else:
            warning = f'WARNING: Unexpected output object: {output_buffer}'
            if console:
                console.write(warning)
            if log:
                log.write(warning)
        inspect_res = self.docker_client.exec_inspect(create_res)
        if 'ExitCode' in inspect_res:
            if inspect_res['ExitCode'] is None:
                raise BuildRunnerContainerError(f'Error running cmd ({cmd}): exit code is None')
            return inspect_res['ExitCode']
        raise BuildRunnerContainerError('Error running cmd: no exit code')

    def run_script(
            self,
            script,
            args='',
            console=None,
    ):
        """
        Run the given script within the container.
        """
        # write temp file with script contents
        script_file_path = tempfile()
        self.run(f'mkdir -p $(dirname {script_file_path})', console=console)
        self.write_to_container_file(script, script_file_path)
        self.run(f'chmod +x {script_file_path}', console=console)

        # execute the script
        return self.run(
            f'{script_file_path} {args}',
            console=console,
        )

    def write_to_container_file(self, content, path):
        """
        Writes contents to the given path within the container.
        """
        # for now, we just take a str
        buf_size = 1024
        for index in range(0, len(content), buf_size):
            self.run(
                f'printf -- "{base64.standard_b64encode(content[index:index + buf_size])}" | base64 --decode >> {path}',
            )

    def _get_status(self):
        """
        Return the status dict for the container.
        """
        status = None
        try:
            status = self.docker_client.inspect_container(
                self.container['Id'],
            )
        except docker.errors.APIError:
            pass
        return status

    def get_ip(self):
        """
        Return the ip address of the running container
        """
        ipaddr = None
        try:
            if self.is_running():
                inspection = self.docker_client.inspect_container(
                    self.container['Id'],
                )
                ipaddr = inspection.get('NetworkSettings', {}).get('IPAddress', None)
        except docker.errors.APIError:
            pass
        return ipaddr

    def is_running(self):
        """
        Return whether the container backed by this Runner is currently
        running.
        """
        status = self._get_status()
        if not status:
            return False
        if 'State' not in status or 'Running' not in status['State']:
            return False
        return status['State']['Running']

    @property
    def exit_code(self):
        """
        Return the exit code of the completed container, or None if it is still
        running.
        """
        status = self._get_status()
        if not status:
            return None
        if 'State' not in status or 'ExitCode' not in status['State']:
            return None
        return status['State']['ExitCode']

    def attach_until_finished(self, stream=None):
        """
        Attach to the container, writing output to the given log stream until
        the container exits.
        """
        docker_socket: socket.SocketIO = self.docker_client.attach_socket(
            self.container['Id'],
        )
        running = self.is_running()
        while running:
            try:
                for line in docker_socket:
                    if stream:
                        stream.write(line)
            except socket.timeout:
                pass
            except ssl.SSLError as ssle:
                if 'The read operation timed out' not in str(ssle):
                    raise
            running = self.is_running()

    def commit(self, stream):
        """
        Commit the ending state of the container as an image, returning the
        image id.
        """
        if self.committed_image:
            return self.committed_image
        if not self.container:
            raise BuildRunnerContainerError('Container not started')
        if self.is_running():
            raise BuildRunnerContainerError('Container is still running')
        stream.write(
            f"Committing build container {self.container['Id']:.10} as an image...\n"
        )
        self.committed_image = self.docker_client.commit(
            self.container['Id'],
        )['Id']
        stream.write(
            f'Resulting build container image: {self.committed_image:.10}\n'
        )
        return self.committed_image
