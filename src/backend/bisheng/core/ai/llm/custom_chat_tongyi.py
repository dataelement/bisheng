from typing import Any, List, Dict
from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import BaseMessage


class CustomChatTongYi(ChatTongyi):
    """
    Custom ChatTongYi Model to handle multi-modal input conversion.
    """

    def _invocation_params(
            self, messages: List[BaseMessage], stop: Any, **kwargs: Any
    ) -> Dict[str, Any]:
        # Get basic call parameters
        params = super()._invocation_params(messages, stop, **kwargs)

        # Iterate through and clean the messages data
        if "messages" in params:
            for msg in params["messages"]:
                # Only when the content is a list (multimodal) is processing required.
                if "content" in msg and isinstance(msg["content"], list):
                    new_content = []
                    for item in msg["content"]:
                        # Check if the image_url is in OpenAI format.
                        if isinstance(item, dict) and item.get("type") == "image_url":
                            # Extract the URL string
                            image_url_data = item.get("image_url")
                            url_str = ""

                            if isinstance(image_url_data, dict):
                                url_str = image_url_data.get("url", "")
                            elif isinstance(image_url_data, str):
                                url_str = image_url_data

                            # Append the cleaned image data
                            if url_str:
                                new_content.append({
                                    "type": "image",
                                    "image": url_str
                                })
                        else:
                            # Non-image data is directly appended
                            new_content.append(item)

                    # Update the message content with cleaned data
                    msg["content"] = new_content

        return params
