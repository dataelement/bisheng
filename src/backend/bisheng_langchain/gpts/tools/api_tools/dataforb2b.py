"""DataForB2B api

B2B data tools for finding and enriching LinkedIn people / companies:
search people & companies by structured filters, natural-language reasoning
search, profile & company enrichment (work/personal email, phone, GitHub),
and a typeahead helper that resolves the exact stored value for a filter.

Drop this file in:
    src/backend/bisheng_langchain/gpts/tools/api_tools/dataforb2b.py
and register the tools in the api_tools ``__init__.py`` (see _DATAFORB2B_TOOLS).
"""
import json
from typing import Any, Optional

import requests
from pydantic import BaseModel, Field

from bisheng_langchain.gpts.tools.api_tools.base import MultArgsSchemaTool

BASE_URL = "https://api.dataforb2b.ai"
REQUEST_TIMEOUT = 120
MAX_RESPONSE_CHARS = 30000


# --- args schemas ---------------------------------------------------------

class SearchPeopleArgs(BaseModel):
    """args_schema for dataforb2b_search_people"""
    filters: str = Field(
        description=(
            "JSON filter object: {\"op\": \"and\", \"conditions\": "
            "[{\"column\", \"type\", \"value\", \"value2?\"}]}. A bare JSON list "
            "of conditions is also accepted. Operators (type): =, !=, like, "
            "not_like, in, not_in, >, >=, <, <=, between. Common people columns: "
            "first_name, last_name, current_title, current_company, "
            "current_company_industry, current_company_size (2-10,11-50,51-200,"
            "201-500,501-1000,1001-5000,5001-10000,10001+), profile_location, "
            "profile_country (ISO-2 UPPER, use GB not UK), skill, school, "
            "years_of_experience, keyword. Resolve free-text values with "
            "dataforb2b_typeahead first when unsure."
        )
    )
    count: int = Field(default=25, description="Number of results (1-100)")
    offset: int = Field(default=0, description="Pagination offset: 0, then 25, 50, …")


class SearchCompanyArgs(BaseModel):
    """args_schema for dataforb2b_search_company"""
    filters: str = Field(
        description=(
            "JSON filter object: {\"op\": \"and\", \"conditions\": "
            "[{\"column\", \"type\", \"value\", \"value2?\"}]}. A bare JSON list "
            "is also accepted. Operators: =, !=, like, not_like, in, not_in, >, "
            ">=, <, <=, between. Common company columns: name, domain, industry "
            "(lowercase e.g. 'software development'), employee_count (1-10,11-50,"
            "51-200,201-500,501-1000,1001-5000,5001-10000,10001+), "
            "country_iso_code (ISO-2), city, region, founded_year, "
            "funding_stage_normalized, has_funding, keyword."
        )
    )
    count: int = Field(default=25, description="Number of results (1-100)")
    offset: int = Field(default=0, description="Pagination offset: 0, then 25, 50, …")


class ReasoningSearchArgs(BaseModel):
    """args_schema for dataforb2b_reasoning_search"""
    query: str = Field(
        description="Natural-language search, e.g. 'CTOs at Series A fintech startups in France'"
    )
    category: str = Field(
        default="people", description="What to search: 'people' or 'companies'"
    )
    max_results: int = Field(default=25, description="Number of results (1-100)")
    session_id: Optional[str] = Field(
        default=None,
        description="Pass the session_id from a previous needs_input/refine turn",
    )
    answers: Optional[str] = Field(
        default=None,
        description="JSON object {question_id: answer} answering a needs_input turn",
    )


class EnrichProfileArgs(BaseModel):
    """args_schema for dataforb2b_enrich_profile"""
    profile_identifier: str = Field(
        description="LinkedIn profile URL, public id (john-doe), or encoded prof_… id"
    )
    enrich_profile: bool = Field(
        default=True, description="Return the full profile (role, experience, skills)"
    )
    enrich_work_email: bool = Field(default=False, description="Find the work email")
    enrich_personal_email: bool = Field(
        default=False, description="Find the personal email"
    )
    enrich_phone: bool = Field(default=False, description="Find the phone number")
    enrich_github: bool = Field(default=False, description="Find the GitHub profile")


class EnrichCompanyArgs(BaseModel):
    """args_schema for dataforb2b_enrich_company"""
    company_identifier: str = Field(
        description="Company domain, name/slug, LinkedIn company URL, or org_… id"
    )


class TypeaheadArgs(BaseModel):
    """args_schema for dataforb2b_typeahead"""
    type: str = Field(
        description=(
            "One of: company, people_industry, company_industry, category, "
            "location, city, region, school, title, skill, investor"
        )
    )
    q: str = Field(description="Prefix/text to autocomplete (1-100 chars)")
    limit: int = Field(default=20, description="Max suggestions (1-20)")


_ARGS_SCHEMAS = {
    "search_people": SearchPeopleArgs,
    "search_company": SearchCompanyArgs,
    "reasoning_search": ReasoningSearchArgs,
    "enrich_profile": EnrichProfileArgs,
    "enrich_company": EnrichCompanyArgs,
    "typeahead": TypeaheadArgs,
}


class DataForB2B(BaseModel):
    """DataForB2B B2B data client (https://api.dataforb2b.ai)."""

    api_key: str = Field(description="DataForB2B API key")

    # --- http helpers -----------------------------------------------------

    def _headers(self) -> dict:
        return {"api_key": self.api_key, "Content-Type": "application/json"}

    def _post(self, path: str, payload: dict) -> str:
        resp = requests.post(
            f"{BASE_URL}{path}",
            json=payload,
            headers=self._headers(),
            timeout=REQUEST_TIMEOUT,
        )
        return self._handle(resp)

    def _get(self, path: str, params: dict) -> str:
        resp = requests.get(
            f"{BASE_URL}{path}",
            params=params,
            headers=self._headers(),
            timeout=REQUEST_TIMEOUT,
        )
        return self._handle(resp)

    @staticmethod
    def _handle(resp: requests.Response) -> str:
        if resp.status_code == 401:
            return "DataForB2B error: invalid or missing API key (401)."
        if resp.status_code == 403:
            return "DataForB2B error: API key lacks permission for this resource (403)."
        if resp.status_code >= 400:
            return f"DataForB2B error ({resp.status_code}): {resp.text[:2000]}"
        return resp.text[:MAX_RESPONSE_CHARS]

    @staticmethod
    def _filters(raw: str) -> dict:
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in 'filters': {e}")
        if isinstance(value, list):
            return {"op": "and", "conditions": value}
        if isinstance(value, dict) and "conditions" not in value and "op" not in value:
            # a single bare condition dict
            return {"op": "and", "conditions": [value]}
        return value

    # --- tools ------------------------------------------------------------

    def search_people(self, filters: str, count: int = 25, offset: int = 0) -> str:
        """Search LinkedIn people / B2B leads by structured filters (job title, company, location, industry, seniority, skills). Use it to find employees at a company, decision-makers (founders, C-suite, VPs, directors), and build a prospect list. Resolve free-text filter values with dataforb2b_typeahead first."""
        return self._post(
            "/search/people",
            {"filters": self._filters(filters), "count": count, "offset": offset,
             "enrich_live": False},
        )

    def search_company(self, filters: str, count: int = 25, offset: int = 0) -> str:
        """Search LinkedIn companies / accounts by structured filters (industry, headcount, location, funding, keywords). Build target-account lists for B2B sales and account-based marketing."""
        return self._post(
            "/search/companies",
            {"filters": self._filters(filters), "count": count, "offset": offset,
             "enrich_live": False},
        )

    def reasoning_search(self, query: str, category: str = "people",
                         max_results: int = 25, session_id: Optional[str] = None,
                         answers: Optional[str] = None) -> str:
        """Natural-language people/company search over the DataForB2B LinkedIn database — describe the audience in plain text (e.g. 'CTOs at Series A fintech startups in France') and the agent builds the filters. May return status 'needs_input' with clarifying questions (free); answer them by re-calling with the returned session_id and an answers JSON."""
        payload: dict = {"query": query, "category": category,
                         "max_results": max_results, "enrich_live": False}
        if session_id:
            payload["session_id"] = session_id
        if answers:
            try:
                payload["answers"] = json.loads(answers) if isinstance(answers, str) else answers
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in 'answers': {e}")
        return self._post("/search/reasoning", payload)

    def enrich_profile(self, profile_identifier: str, enrich_profile: bool = True,
                       enrich_work_email: bool = False,
                       enrich_personal_email: bool = False,
                       enrich_phone: bool = False,
                       enrich_github: bool = False) -> str:
        """Enrich a professional profile from a LinkedIn URL — returns the full profile (current role, experience, skills) plus work email, personal email, phone and GitHub. Works as an email finder for lead enrichment and cold outreach. Charged only for the flags you enable; at least one must be true."""
        flags = {
            "enrich_profile": enrich_profile,
            "enrich_work_email": enrich_work_email,
            "enrich_personal_email": enrich_personal_email,
            "enrich_phone": enrich_phone,
            "enrich_github": enrich_github,
        }
        if not any(flags.values()):
            flags["enrich_profile"] = True
        return self._post("/enrich/profile", {"profile_identifier": profile_identifier, **flags})

    def enrich_company(self, company_identifier: str) -> str:
        """Enrich a company from its domain, name or LinkedIn company URL — firmographics, headcount/size, industry, domain and social profiles. Account enrichment for B2B sales and CRM."""
        return self._post("/enrich/company", {"company_identifier": company_identifier})

    def typeahead(self, type: str, q: str, limit: int = 20) -> str:
        """Resolve the exact stored value for a free-text filter before searching (results ordered by popularity). type is one of: company, people_industry, company_industry, category, location, city, region, school, title, skill, investor. Use it when unsure which value to filter on, or when a search returns few/no results."""
        return self._get("/typeahead", {"type": type, "q": q, "limit": limit})

    # --- registration -----------------------------------------------------

    @classmethod
    def get_api_tool(cls, name: str, **kwargs: Any) -> "BaseTool":
        attr_name = name.split("_", 1)[-1]  # dataforb2b_search_people -> search_people
        instance = cls(**kwargs)
        class_method = getattr(instance, attr_name)
        return MultArgsSchemaTool(
            name=name,
            description=class_method.__doc__,
            func=class_method,
            args_schema=_ARGS_SCHEMAS[attr_name],
        )
