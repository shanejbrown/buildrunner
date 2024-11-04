"""
Copyright 2021 Adobe
All Rights Reserved.

NOTICE: Adobe permits you to use, modify, and distribute this file in accordance
with the terms of the Adobe license agreement accompanying it.
"""

import json
import logging
import os
import re
import tarfile
import tempfile

import docker
import docker.errors

from buildrunner.errors import (
    BuildRunnerProcessingError,
)

from buildrunner.docker import get_dockerfile, new_client, force_remove_container

logger = logging.getLogger(__name__)

NO_CACHE_DEFAULT = False
RM_DEFAULT = True
PULL_DEFAULT = True


def build_image(
    path=None,
    inject=None,
    dockerfile=None,
    dockerd_url=None,
    timeout=None,
    docker_registry=None,
    temp_dir=None,
    console=None,
    nocache=NO_CACHE_DEFAULT,
    cache_from=None,
    rm=RM_DEFAULT,
    pull=PULL_DEFAULT,
    buildargs=None,
    platform=None,
    target=None,
):
    """
    Build a Docker image using the DockerBuilder class.
    Args:
        path (str): Path to the build context.
        inject (dict): Dictionary of files to inject into the build context.
        dockerfile (str): Path to the Dockerfile to use.
        dockerd_url (str): URL to the Docker daemon.
        timeout (int): Timeout for the Docker client.
        docker_registry (str): Docker registry to use.
        temp_dir (str): Temporary directory to use.
        console (object): Console object to write output to.
        nocache (bool): Whether to use the Docker cache.
        cache_from (list): List of images to use as cache sources.
        rm (bool): Whether to remove intermediate containers.
        pull (bool): Whether to pull images from the registry.
        buildargs (dict): Build arguments to pass to the Docker client.
        platform (str): Platform to build the image for.
        target (str): Target stage to build.
    Returns:
        str: The ID of the built image.
    """
    logger.info("Using legacy builder")
    image = None
    builder = DockerBuilder(
        path,
        inject=inject,
        dockerfile=dockerfile,
        dockerd_url=dockerd_url,
        timeout=timeout,
        docker_registry=docker_registry,
        temp_dir=temp_dir,
    )
    try:
        exit_code = builder.build(
            console=console,
            nocache=nocache,
            cache_from=cache_from,
            rm=rm,
            pull=pull,
            buildargs=buildargs,
            platform=platform,
            target=target,
        )
        if exit_code != 0 or not builder.image:
            raise BuildRunnerProcessingError("Error building image")
        image = builder.image
    finally:
        builder.cleanup()
    return image


class DockerBuilder:  # pylint: disable=too-many-instance-attributes
    """
    An object that manages and orchestrates building a Docker image from
    a Dockerfile.
    """

    def __init__(
        self,
        path=None,
        inject=None,
        dockerfile=None,
        dockerd_url=None,
        timeout=None,
        docker_registry=None,
        temp_dir=None,
    ):  # pylint: disable=too-many-arguments
        self.path = path
        self.inject = inject
        self.temp_dir = temp_dir
        self.dockerfile = None
        self.cleanup_dockerfile = False

        self.dockerfile, self.cleanup_dockerfile = get_dockerfile(
            dockerfile, self.temp_dir
        )

        self.docker_client = new_client(
            dockerd_url=dockerd_url,
            timeout=timeout,
        )
        self.docker_registry = docker_registry
        self._image = None
        self.intermediate_containers = []

    @staticmethod
    def _sanitize_buildargs(buildargs=None):
        """
        Ensure that buildargs are correct for the Docker API.

        Args:

            :buildargs: (dict): unsanitized arguments to be passed to the Docker client.

        Returns:

            :dict: sanitized arguments to be passed to the Docker client.
        """
        if not isinstance(buildargs, dict):
            raise TypeError("buildargs must be a dictionary of keys/values")

        return {k: str(v) for k, v in list(buildargs.items())}

    # pylint: disable=too-many-branches,too-many-locals,too-many-arguments,invalid-name
    def build(
        self,
        console=None,
        nocache=NO_CACHE_DEFAULT,
        cache_from=None,
        rm=RM_DEFAULT,
        pull=PULL_DEFAULT,
        buildargs=None,
        platform=None,
        target=None,
    ):
        """
        Run a docker build using the configured context, constructing the
        context tar file if necessary.
        """
        logger.info("Using legacy builder")
        if cache_from is None:
            cache_from = []
        if buildargs is None:
            buildargs = {}

        # Always add default registry to build args
        buildargs["DOCKER_REGISTRY"] = self.docker_registry
        stream = None

        # create our own tar file, injecting the appropriate paths
        # pylint: disable=consider-using-with
        if self.inject or not self.path:
            logger.info(
                "[Warning] When injecting files into the build context the .dockerignore is not used."
            )

            _fileobj = tempfile.NamedTemporaryFile(dir=self.temp_dir)
            with tarfile.open(mode="w", fileobj=_fileobj) as tfile:
                if self.path:
                    tfile.add(self.path, arcname=".")
                if self.inject:
                    for to_inject, dest in self.inject.items():
                        tfile.add(to_inject, arcname=dest)
                if self.dockerfile:
                    tfile.add(self.dockerfile, arcname="./Dockerfile")
            _fileobj.seek(0)

            stream = self.docker_client.build(
                path=None,
                nocache=nocache,
                cache_from=cache_from,
                custom_context=True,
                fileobj=_fileobj,
                rm=rm,
                pull=pull,
                buildargs=self._sanitize_buildargs(buildargs),
                platform=platform,
                target=target,
            )
        else:
            stream = self.docker_client.build(
                path=self.path,
                nocache=nocache,
                cache_from=cache_from,
                rm=rm,
                pull=pull,
                buildargs=self._sanitize_buildargs(buildargs),
                platform=platform,
                target=target,
                dockerfile=self.dockerfile,
            )

        # monitor output for logs and status
        exit_code = 0
        msg_buffer = ""
        for msg_str in stream:  # pylint: disable=too-many-nested-blocks
            for msg in msg_str.decode("utf-8").split("\n"):
                if msg:
                    msg_buffer += msg
                    try:
                        # there is a limit on the chars returned in the stream
                        # generator, so if we don't have a valid json message
                        # here we get the next msg and append to the current
                        # one
                        json_msg = json.loads(msg_buffer)
                        msg_buffer = ""
                    except ValueError:
                        continue
                    if "stream" in json_msg:
                        # capture intermediate containers for cleanup later
                        # the command line 'docker build' has a '--force-rm' option,
                        # but that isn't available in the python client
                        container_match = re.search(
                            r" ---> Running in ([0-9a-f]+)",
                            json_msg["stream"],
                        )
                        if container_match:
                            self.intermediate_containers.append(
                                container_match.group(1)
                            )

                        # capture the resulting image
                        image_match = re.search(
                            r"Successfully built ([0-9a-f]+)",
                            json_msg["stream"],
                        )
                        if image_match:
                            self.image = image_match.group(1)

                        if console:
                            console.write(json_msg["stream"])
                    if "error" in json_msg:
                        exit_code = 1
                        if "errorDetail" in json_msg:
                            if "message" in json_msg["errorDetail"] and console:
                                console.write(f"{json_msg['errorDetail']['message']}\n")

        return exit_code

    def cleanup(self):
        """
        Cleanup the docker build environment.
        """
        # cleanup the generated dockerfile if present
        if self.cleanup_dockerfile:
            if self.dockerfile and os.path.exists(self.dockerfile):
                os.remove(self.dockerfile)

        # iterate through and destroy intermediate containers
        for container in self.intermediate_containers:
            try:
                force_remove_container(self.docker_client, container)
            except docker.errors.APIError as err:
                logger.debug(
                    f"Error removing intermediate container {container}: {err}"
                )
