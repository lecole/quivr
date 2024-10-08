import time
import os
from enum import Enum

from fastapi import HTTPException
from quivr_api.logger import get_logger
from quivr_api.modules.models.entity.model import Model
from quivr_api.modules.models.service.model_service import ModelService
from quivr_api.modules.user.entity.user_identity import UserIdentity
from quivr_api.modules.user.service.user_usage import UserUsage
from quivr_core.config import RetrievalConfig

logger = get_logger(__name__)


class RetrievalConfigPathEnv(Enum):
    CHAT_WITH_LLM = ("CHAT_LLM_CONFIG_PATH", "config/chat_llm_config.yaml")
    RAG = ("BRAIN_CONFIG_PATH", "config/retrieval_config_workflow.yaml")

    @property
    def env_var(self) -> str:
        return self.value[0]

    @property
    def default_path(self) -> str:
        return self.value[1]


def get_config_file_path(
    config_path_env: RetrievalConfigPathEnv, current_path: str | None = None
) -> str:
    # Get the environment variable or fallback to the default path
    _path = os.getenv(config_path_env.env_var, config_path_env.default_path)

    if not current_path:
        return _path

    return os.path.join(current_path, _path)


def load_and_merge_retrieval_configuration(
    config_file_path: str, sqlmodel: Model
) -> RetrievalConfig:
    retrieval_config = RetrievalConfig.from_yaml(config_file_path)
    field_mapping = {
        "env_variable_name": "env_variable_name",
        "endpoint_url": "llm_base_url",
    }

    retrieval_config.llm_config.set_from_sqlmodel(
        sqlmodel=sqlmodel, mapping=field_mapping
    )

    retrieval_config.llm_config.set_llm_model(sqlmodel.name)

    return retrieval_config


# TODO: rewrite
async def find_model_and_generate_metadata(
    brain_model: str | None,
    model_service: ModelService,
) -> Model:
    model = await model_service.get_model(brain_model)
    if model is None:
        model = await model_service.get_default_model()
    return model


def update_user_usage(usage: UserUsage, user_settings, cost: int = 100):
    """Checks the user requests limit.
    It checks the user requests limit and raises an exception if the user has reached the limit.
    By default, the user has a limit of 100 requests per month. The limit can be increased by upgrading the plan.

    Args:
        user (UserIdentity): User object
        model (str): Model name for which the user is making the request

    Raises:
        HTTPException: Raises a 429 error if the user has reached the limit.
    """

    date = time.strftime("%Y%m%d")

    monthly_chat_credit = user_settings.get("monthly_chat_credit", 100)
    montly_usage = usage.get_user_monthly_usage(date)

    if int(montly_usage + cost) > int(monthly_chat_credit):
        raise HTTPException(
            status_code=429,  # pyright: ignore reportPrivateUsage=none
            detail=f"You have reached your monthly chat limit of {monthly_chat_credit} requests per months. Please upgrade your plan to increase your monthly chat limit.",
        )
    else:
        usage.handle_increment_user_request_count(date, cost)
        pass


async def check_and_update_user_usage(
    user: UserIdentity, model_name: str, model_service: ModelService
):
    """Check user limits and raises if user reached his limits:
    1. Raise if one of the conditions :
       - User doesn't have access to brains
       - Model of brain is not is user_settings.models
       - Latest sum_30d(user_daily_user) < user_settings.max_monthly_usage
       - Check sum(user_settings.daily_user_count)+ model_price <  user_settings.monthly_chat_credits
    2. Updates user usage
    """
    # TODO(@aminediro) : THIS is bug prone, should retrieve it from DB here
    user_usage = UserUsage(id=user.id, email=user.email)
    user_settings = user_usage.get_user_settings()

    # Get the model to use
    model = await model_service.get_model(model_name)
    logger.info(f"Model 🔥: {model}")
    if model is None:
        model = await model_service.get_default_model()
        logger.info(f"Model 🔥: {model}")

    # Raises HTTP if user usage exceeds limits
    update_user_usage(user_usage, user_settings, model.price)  # noqa: F821
    return model
