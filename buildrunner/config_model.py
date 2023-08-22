"""
Copyright 2023 Adobe
All Rights Reserved.

NOTICE: Adobe permits you to use, modify, and distribute this file in accordance
with the terms of the Adobe license agreement accompanying it.
"""

from typing import Optional
from pydantic import BaseModel


class StepBuild(BaseModel):
    """ Build model within a step """
    path: Optional[str]
    dockerfile: Optional[str]
    pull: Optional[bool]
    platform: Optional[str]
    platforms: Optional[list[str]]


class StepPushDict(BaseModel):
    """ Push model within a step """
    repository: str
    tags: list[str]


class Step(BaseModel):
    """ Step model """
    build: Optional[StepBuild]
    push: Optional[StepPushDict | list[str | StepPushDict] | str]

    def is_multi_platform(self):
        """
        Check if the step is a multi-platform build step
        """
        return self.build is not None and \
            self.build.platforms is not None


class Config(BaseModel):
    """ Top level config model """
    version: Optional[float]
    steps: dict[str, Step]

    def __init__(self, **data) -> None:
        super().__init__(**data)
        self.validate()

    def has_multi_platform_build(self):
        """
        Check if the config file has multi-platform build steps

        Returns:
            bool: True if the config file has multi-platform build steps, False otherwise
        """
        for step in self.steps.values():
            if step.is_multi_platform():
                return True
        return False

    def validate_push(self,
                      push: StepPushDict | list[str | StepPushDict] | str,
                      mp_push_tags: set[str],
                      step_name: str,
                      update_mp_push_tags: bool = True):
        """
        Validate push step

        Args:
            push (StepPushDict | list[str | StepPushDict] | str): Push step
            mp_push_tags (set[str]): Set of all tags used in multi-platform build steps
            step_name (str): Name of the step
            update_mp_push_tags (bool, optional): Whether to update the set of tags used in multi-platform steps.

        Raises:
            ValueError: If the config file is invalid
        """
        # Check for valid push section, duplicate mp tags are not allowed
        if push is not None:
            name = None
            names = None
            if isinstance(push, str):
                name = push
                if ":" not in name:
                    name = f'{name}:latest'

            if isinstance(push, StepPushDict):
                names = [f"{push.repository}:{tag}" for tag in push.tags]

            if names is not None:
                for current_name in names:
                    if current_name in mp_push_tags:
                        # raise ValueError(f'Cannot specify duplicate tag {current_name} in build step {step_name}')
                        raise ValueError(f'Cannot specify duplicate tag {current_name} in build step {step_name}')

            if name is not None and name in mp_push_tags:
                # raise ValueError(f'Cannot specify duplicate tag {name} in build step {step_name}')
                raise ValueError(f'Cannot specify duplicate tag {name} in build step {step_name}')

            if update_mp_push_tags and names is not None:
                mp_push_tags.update(names)

            if update_mp_push_tags and name is not None:
                mp_push_tags.add(name)

    def validate_multi_platform_build(self, mp_push_tags: set[str]):
        """
        Validate multi-platform build steps

        Args:
            mp_push_tags (set[str]): Set of all tags used in multi-platform build steps

        Raises:
            ValueError | pydantic.ValidationError: If the config file is invalid
        """
        # Iterate through each step
        for step_name, step in self.steps.items():
            if step.is_multi_platform():
                if step.build.platform is not None:
                    raise ValueError(f'Cannot specify both platform ({step.build.platform}) and '
                                     f'platforms ({step.build.platforms}) in build step {step_name}')

                if not isinstance(step.build.platforms, list):
                    raise ValueError(f'platforms must be a list in build step {step_name}')

                # Check for valid push section, duplicate mp tags are not allowed
                self.validate_push(step.push, mp_push_tags, step_name)

    def validate(self):
        """
        Validate the config file

        Raises:
            ValueError | pydantic.ValidationError : If the config file is invalid
        """
        if self.has_multi_platform_build():
            mp_push_tags = set()
            self.validate_multi_platform_build(mp_push_tags)

            # Validate that all tags are unique across all multi-platform step
            for step_name, step in self.steps.items():

                # Check that there are no single platform tags that match multi-platform tags
                if not step.is_multi_platform():
                    if step.push is not None:
                        self.validate_push(push=step.push,
                                           mp_push_tags=mp_push_tags,
                                           step_name=step_name,
                                           update_mp_push_tags=False)
