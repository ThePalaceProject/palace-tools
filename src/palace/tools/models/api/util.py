from pydantic import BaseModel, ConfigDict, Extra


def _snake_to_camel_case(name: str) -> str:
    """Convert from Python snake case to JavaScript lower camel case."""
    if new_name := "".join(word.title() for word in name.split("_") if word):
        return f"{new_name[0].lower()}{new_name[1:]}"
    else:
        raise ValueError("Name ('{name}') may not consist entirely of underscores.")


class ApiBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_snake_to_camel_case,
        populate_by_name=True,
        extra=Extra.allow,
    )
