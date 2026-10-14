"""Jira entity schemas.

Entity schemas for Jira Projects, Issues, and Zephyr Scale test management entities.

Zephyr Scale is a test management plugin for Jira that creates separate entities
(Test Cases, Test Cycles, Test Plans) accessible via the Zephyr Scale API.
"""

from datetime import datetime
from typing import Optional

from pydantic import computed_field

from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._contextd_field import ContextDField


class JiraProjectEntity(BaseEntity):
    """Schema for a Jira Project.

    Reference:
        https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-projects/
    """

    project_id: str = ContextDField(
        ..., description="Unique numeric identifier for the project.", is_entity_id=True
    )
    project_name: str = ContextDField(
        ..., description="Display name of the project.", embeddable=True, is_name=True
    )
    project_key: str = ContextDField(
        ..., description="Unique key of the project (e.g., 'PROJ').", embeddable=True
    )
    description: Optional[str] = ContextDField(
        None, description="Description of the project.", embeddable=True
    )
    web_url_value: Optional[str] = ContextDField(
        None, description="Link to the project in Jira.", embeddable=False, unhashable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """UI link for the Jira project."""
        return self.web_url_value or ""


class JiraIssueEntity(BaseEntity):
    """Schema for a Jira Issue.

    Reference:
        https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/
    """

    issue_id: str = ContextDField(
        ..., description="Unique identifier for the issue.", is_entity_id=True
    )
    issue_key: str = ContextDField(
        ..., description="Jira key for the issue (e.g. 'PROJ-123').", embeddable=True
    )
    summary: str = ContextDField(
        ..., description="Short summary field of the issue.", embeddable=True, is_name=True
    )
    description: Optional[str] = ContextDField(
        None, description="Detailed description of the issue.", embeddable=True
    )
    status: Optional[str] = ContextDField(
        None, description="Current workflow status of the issue.", embeddable=True
    )
    issue_type: Optional[str] = ContextDField(
        None, description="Type of the issue (bug, task, story, etc.).", embeddable=True
    )
    project_key: str = ContextDField(
        ..., description="Key of the project that owns this issue.", embeddable=True
    )
    created_time: datetime = ContextDField(
        ..., description="Timestamp when the issue was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="Timestamp when the issue was last updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None, description="Link to the issue in Jira.", embeddable=False, unhashable=True
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """UI link for the Jira issue."""
        return self.web_url_value or ""


# =============================================================================
# Zephyr Scale Entities
# =============================================================================
# These entities are from the Zephyr Scale test management plugin for Jira.
# They are accessed via the Zephyr Scale API (https://api.zephyrscale.smartbear.com/v2),
# not the Jira REST API, and require a separate Zephyr Scale API token.


class ZephyrTestCaseEntity(BaseEntity):
    """Schema for a Zephyr Scale Test Case.

    Test cases have keys in the format PROJECT-T### (e.g., PROJ-T1, PROJ-T2).

    Reference:
        https://support.smartbear.com/zephyr-scale-cloud/api-docs/#tag/Test-Cases
    """

    test_case_id: str = ContextDField(
        ..., description="Unique internal identifier for the test case.", is_entity_id=True
    )
    test_case_key: str = ContextDField(
        ...,
        description="Zephyr Scale key for the test case (e.g., 'PROJ-T1').",
        embeddable=True,
    )
    name: str = ContextDField(
        ..., description="Name/title of the test case.", embeddable=True, is_name=True
    )
    objective: Optional[str] = ContextDField(
        None, description="Objective or purpose of the test case.", embeddable=True
    )
    precondition: Optional[str] = ContextDField(
        None, description="Preconditions required before executing the test.", embeddable=True
    )
    status_name: Optional[str] = ContextDField(
        None,
        description="Current status of the test case (e.g., Draft, Approved).",
        embeddable=True,
    )
    priority_name: Optional[str] = ContextDField(
        None, description="Priority level of the test case.", embeddable=True
    )
    folder_path: Optional[str] = ContextDField(
        None, description="Folder path where the test case is organized.", embeddable=True
    )
    project_key: str = ContextDField(
        ..., description="Key of the Jira project this test case belongs to.", embeddable=True
    )
    created_time: datetime = ContextDField(
        ..., description="Timestamp when the test case was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="Timestamp when the test case was last updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="Link to the test case in Zephyr Scale.",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """UI link for the Zephyr Scale test case."""
        return self.web_url_value or ""


class ZephyrTestCycleEntity(BaseEntity):
    """Schema for a Zephyr Scale Test Cycle.

    Test cycles have keys in the format PROJECT-R### (e.g., PROJ-R1, PROJ-R2).
    They represent a collection of test executions for a specific testing iteration.

    Reference:
        https://support.smartbear.com/zephyr-scale-cloud/api-docs/#tag/Test-Cycles
    """

    test_cycle_id: str = ContextDField(
        ..., description="Unique internal identifier for the test cycle.", is_entity_id=True
    )
    test_cycle_key: str = ContextDField(
        ...,
        description="Zephyr Scale key for the test cycle (e.g., 'PROJ-R1').",
        embeddable=True,
    )
    name: str = ContextDField(
        ..., description="Name/title of the test cycle.", embeddable=True, is_name=True
    )
    description: Optional[str] = ContextDField(
        None, description="Description of the test cycle.", embeddable=True
    )
    status_name: Optional[str] = ContextDField(
        None,
        description="Current status of the test cycle (e.g., Not Executed, In Progress, Done).",
        embeddable=True,
    )
    folder_path: Optional[str] = ContextDField(
        None, description="Folder path where the test cycle is organized.", embeddable=True
    )
    project_key: str = ContextDField(
        ..., description="Key of the Jira project this test cycle belongs to.", embeddable=True
    )
    created_time: datetime = ContextDField(
        ..., description="Timestamp when the test cycle was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="Timestamp when the test cycle was last updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="Link to the test cycle in Zephyr Scale.",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """UI link for the Zephyr Scale test cycle."""
        return self.web_url_value or ""


class ZephyrTestPlanEntity(BaseEntity):
    """Schema for a Zephyr Scale Test Plan.

    Test plans have keys in the format PROJECT-P### (e.g., PROJ-P1, PROJ-P2).
    They represent a high-level collection of test cycles for release planning.

    Reference:
        https://support.smartbear.com/zephyr-scale-cloud/api-docs/#tag/Test-Plans
    """

    test_plan_id: str = ContextDField(
        ..., description="Unique internal identifier for the test plan.", is_entity_id=True
    )
    test_plan_key: str = ContextDField(
        ...,
        description="Zephyr Scale key for the test plan (e.g., 'PROJ-P1').",
        embeddable=True,
    )
    name: str = ContextDField(
        ..., description="Name/title of the test plan.", embeddable=True, is_name=True
    )
    objective: Optional[str] = ContextDField(
        None, description="Objective or purpose of the test plan.", embeddable=True
    )
    status_name: Optional[str] = ContextDField(
        None,
        description="Current status of the test plan (e.g., Draft, Approved, Archived).",
        embeddable=True,
    )
    folder_path: Optional[str] = ContextDField(
        None, description="Folder path where the test plan is organized.", embeddable=True
    )
    project_key: str = ContextDField(
        ..., description="Key of the Jira project this test plan belongs to.", embeddable=True
    )
    created_time: datetime = ContextDField(
        ..., description="Timestamp when the test plan was created.", is_created_at=True
    )
    updated_time: datetime = ContextDField(
        ..., description="Timestamp when the test plan was last updated.", is_updated_at=True
    )
    web_url_value: Optional[str] = ContextDField(
        None,
        description="Link to the test plan in Zephyr Scale.",
        embeddable=False,
        unhashable=True,
    )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """UI link for the Zephyr Scale test plan."""
        return self.web_url_value or ""
