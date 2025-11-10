# Copyright 2022-2023 XProbe Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ._compat import Field

none_field = Field(None)

stream_interval_field = Field(default=2)

echo_field = Field(
    default=False,
    description="Whether to echo the prompt in the generated text. Useful for chatbots.",
)

logprobs_field = Field(
    default=None,
    ge=0,
    description="The number of logprobs to generate. If None, no logprobs are generated.",
)

# Note: changed from 1024 to None to let the model output maximum content which has better user experience
max_tokens_field = Field(
    default=None,
    ge=1,
    description="The maximum number of tokens to generate.",
)

temperature_field = Field(
    default=0.8,
    ge=0.0,
    le=2.0,
    description="Adjust the randomness of the generated text.\n\n"
    "Temperature is a hyperparameter that controls the randomness of the generated text. "
    "It affects the probability distribution of the model's output tokens. "
    "A higher temperature (e.g., 1.5) makes the output more random and creative, "
    "while a lower temperature (e.g., 0.5) makes the output more focused, deterministic, and conservative. "
    "The default value is 0.8, which provides a balance between randomness and determinism. "
    "At the extreme, a temperature of 0 will always pick the most likely next token, "
    "leading to identical outputs in each run.",
)

top_p_field = Field(
    default=0.95,
    ge=0.0,
    le=1.0,
    description="Limit the next token selection to a subset of tokens with "
    "a cumulative probability above a threshold P.\n\n"
    "Top-p sampling, also known as nucleus sampling, "
    "is another text generation method that selects the next token from a subset of tokens "
    "that together have a cumulative probability of at least p. "
    "This method provides a balance between diversity and quality by considering "
    "both the probabilities of tokens and the number of tokens to sample from. "
    "A higher value for top_p (e.g., 0.95) will lead to more diverse text, "
    "while a lower value (e.g., 0.5) will generate more focused and conservative text.",
)

stop_field = Field(
    default=[],
    description="A list of tokens at which to stop generation. If None, no stop tokens are used.",
)

stream_field = Field(
    default=False,
    description="Whether to stream the results as they are generated. Useful for chatbots.",
)

stream_option_field = Field(
    default={
        "include_usage": False,
    },
    description="If set, an additional chunk will be streamed before the `data: [DONE]` message.",
)

top_k_field = Field(
    default=40,
    ge=0,
    description="Limit the next token selection to the K most probable tokens.\n\n"
    "Top-k sampling is a text generation method that selects the next token "
    "only from the top k most likely tokens predicted by the model. "
    "It helps reduce the risk of generating low-probability or nonsensical tokens, "
    "but it may also limit the diversity of the output. "
    "A higher value for top_k (e.g., 100) will consider more tokens and lead to more diverse text, "
    "while a lower value (e.g., 10) will focus on the most probable tokens and "
    "generate more conservative text.",
)

repeat_penalty_field = Field(
    default=1.1,
    ge=0.0,
    description="A penalty applied to each token that is already generated. "
    "This helps prevent the model from repeating itself.\n\n"
    "Repeat penalty is a hyperparameter used to penalize the repetition of token sequences "
    "during text generation. "
    "It helps prevent the model from generating repetitive or monotonous text. "
    "A higher value (e.g., 1.5) will penalize repetitions more strongly, "
    "while a lower value (e.g., 0.9) will be more lenient.",
)

presence_penalty_field = Field(
    default=0.0,
    ge=-2.0,
    le=2.0,
    description="Positive values penalize new tokens based on whether they appear in the text so far, "
    "increasing the model's likelihood to talk about new topics.",
)

frequency_penalty_field = Field(
    default=0.0,
    ge=-2.0,
    le=2.0,
    description="Positive values penalize new tokens based on their existing frequency in the text so far, "
    "decreasing the model's likelihood to repeat the same line verbatim.",
)

mirostat_mode_field = Field(
    default=0,
    ge=0,
    le=2,
    description="Enable Mirostat constant-perplexity algorithm of the specified version (1 or 2; 0 = disabled)",
)

mirostat_tau_field = Field(
    default=5.0,
    ge=0.0,
    le=10.0,
    description="Mirostat target entropy, i.e. the target perplexity - lower values produce focused and coherent text, "
    "larger values produce more diverse and less coherent text",
)

mirostat_eta_field = Field(
    default=0.1, ge=0.001, le=1.0, description="Mirostat learning rate"
)
