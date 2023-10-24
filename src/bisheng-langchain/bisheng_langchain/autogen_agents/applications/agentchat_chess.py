import chess
import chess.svg
import autogen

config_list_gpt4 = autogen.config_list_from_json(
    "OAI_CONFIG_LIST",
    filter_dict={
        "model": ["gpt-4", "gpt4", "gpt-4-32k", "gpt-4-32k-0314", "gpt-4-32k-v0314"],
    },
)


from collections import defaultdict
from typing import Any, Dict, List, Optional, Union

sys_msg = """You are an AI-powered chess board agent.
You translate user's natural language input into legal UCI moves.
You should only reply with a UCI move string extracted from user's input."""

class BoardAgent(autogen.AssistantAgent):
    board: chess.Board
    correct_move_messages: Dict[autogen.Agent, List[Dict]]

    def __init__(self, board: chess.Board):
        super().__init__(
            name="BoardAgent",
            system_message=sys_msg,
            llm_config={"temperature": 0.0, "config_list": config_list_gpt4},
            max_consecutive_auto_reply=10,
        )
        self.register_reply(autogen.ConversableAgent, BoardAgent._generate_board_reply)
        self.board = board
        self.correct_move_messages = defaultdict(list)

    def _generate_board_reply(
        self,
        messages: Optional[List[Dict]] = None,
        sender: Optional[autogen.Agent] = None,
        config: Optional[Any] = None,
    ) -> Union[str, Dict, None]:
        message = messages[-1]
        # extract a UCI move from player's message
        reply = self.generate_reply(self.correct_move_messages[sender] + [message], sender, exclude=[BoardAgent._generate_board_reply])
        uci_move = reply if isinstance(reply, str) else str(reply["content"])
        try:
            self.board.push_uci(uci_move)
        except ValueError as e:
            # invalid move
            return True, f"Error: {e}"
        else:
            # valid move
            m = chess.Move.from_uci(uci_move)
            display(chess.svg.board(self.board, arrows=[(m.from_square, m.to_square)], fill={m.from_square: "gray"}, size=200))
            self.correct_move_messages[sender].extend([message, self._message_to_dict(uci_move)])
            self.correct_move_messages[sender][-1]["role"] = "assistant"
            return True, uci_move


sys_msg_tmpl = """Your name is {name} and you are a chess player.
You are playing against {opponent_name}.
You are playing as {color}.
You communicate your move using universal chess interface language.
You also chit-chat with your opponent when you communicate a move to light up the mood.
You should make sure both you and the opponent are making legal moves.
Do not apologize for making illegal moves."""


class ChessPlayerAgent(autogen.AssistantAgent):

    def __init__(
        self,
        color: str,
        board_agent: BoardAgent,
        max_turns: int,
        **kwargs,
    ):
        if color not in ["white", "black"]:
            raise ValueError(f"color must be either white or black, but got {color}")
        opponent_color = "black" if color == "white" else "white"
        name = f"Player {color}"
        opponent_name = f"Player {opponent_color}"
        sys_msg = sys_msg_tmpl.format(
            name=name,
            opponent_name=opponent_name,
            color=color,
        )
        super().__init__(
            name=name,
            system_message=sys_msg,
            max_consecutive_auto_reply=max_turns,
            **kwargs,
        )
        self.register_reply(BoardAgent, ChessPlayerAgent._generate_reply_for_board, config=board_agent.board)
        self.register_reply(ChessPlayerAgent, ChessPlayerAgent._generate_reply_for_player, config=board_agent)
        self.update_max_consecutive_auto_reply(board_agent.max_consecutive_auto_reply(), board_agent)

    def _generate_reply_for_board(
        self,
        messages: Optional[List[Dict]] = None,
        sender: Optional[autogen.Agent] = None,
        config: Optional[chess.Board] = None,
    ) -> Union[str, Dict, None]:
        board = config
        # add a system message about the current state of the board.
        board_state_msg = [{"role": "system", "content": f"Current board:\n{board}"}]
        last_message = messages[-1]
        if last_message["content"].startswith("Error"):
            # try again
            last_message["role"] = "system"
            return True, self.generate_reply(messages + board_state_msg, sender, exclude=[ChessPlayerAgent._generate_reply_for_board])
        else:
            return True, None

    def _generate_reply_for_player(
        self,
        messages: Optional[List[Dict]] = None,
        sender: Optional[autogen.Agent] = None,
        config: Optional[BoardAgent] = None,
    ) -> Union[str, Dict, None]:
        board_agent = config
        # add a system message about the current state of the board.
        board_state_msg = [{"role": "system", "content": f"Current board:\n{board_agent.board}"}]
        # propose a reply which will be sent to the board agent for verification.
        message = self.generate_reply(messages + board_state_msg, sender, exclude=[ChessPlayerAgent._generate_reply_for_player])
        if message is None:
            return True, None
        # converse with the board until a legal move is made or max allowed retries.
        # change silent to False to see that conversation.
        self.initiate_chat(board_agent, clear_history=False, message=message, silent=self.human_input_mode == "NEVER")
        # last message sent by the board agent
        last_message = self._oai_messages[board_agent][-1]
        if last_message["role"] == "assistant":
            # didn't make a legal move after a limit times of retries.
            print(f"{self.name}: I yield.")
            return True, None
        return True, self._oai_messages[board_agent][-2]


max_turn = 10

board = chess.Board()
board_agent = BoardAgent(board=board)
player_black = ChessPlayerAgent(
    color="black",
    board_agent=board_agent,
    max_turns=max_turn,
    llm_config={"temperature": 0.5, "seed": 1, "config_list": config_list_gpt4},
)
player_white = ChessPlayerAgent(
    color="white",
    board_agent=board_agent,
    max_turns=max_turn,
    llm_config={"temperature": 0.5, "seed": 2, "config_list": config_list_gpt4},
)


player_black.initiate_chat(player_white, message="Your turn.")
