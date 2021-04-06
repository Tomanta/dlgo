import copy
from dlgo.gotypes import Player
from dlgo import zobrist

class Move():
    """ Any action a player can play on a turn -
        is_play, is_pass, or is_resign - will be set.

        Usually the constructor will not be called, instead one of the
        "play", "pass_turn", or "resign" options will be called and
        create the object
    """
    def __init__(self, point=None, is_pass=False, is_resign=False):
        assert (point is not None) ^ is_pass ^ is_resign # check that at least one option is picked
        self.point = point
        self.is_play = (self.point is not None) # only placing pieces is a play
        self.is_pass = is_pass
        self.is_resign = is_resign

    @classmethod
    def play(cls, point):
        """ Place a stone on the board """
        return Move(point=point)
    
    @classmethod
    def pass_turn(cls):
        """ Passes the turn """
        return Move(is_pass=True)

    @classmethod
    def resign(cls):
        """ Resigns the game """
        return Move(is_resign=True)

class GoString():
    """ A chain of connected stones of the same color.
        Unlike the slow version, this uses frozensets to make them immutable."""
    def __init__(self, color, stones, liberties):
        self.color = color
        self.stones = frozenset(stones)
        self.liberties = frozenset(liberties)

    def without_liberty(self, point):
        """ This replaces remove_liberty in the slow version."""
        new_liberties = self.liberties - set([point])
        return GoString(self.color, self.stones, new_liberties)

    def with_liberty(self, point):
        """ This replaces add_libery in the slow version."""
        new_liberties = self.liberities | set([point])
        return GoString(self.color, self.stones, new_liberties)
    
    def merged_with(self, go_string):
        """ Returns a new Go String containing stones in both strings """
        assert go_string.color == self.color
        combined_stones = self.stones | go_string.stones
        return GoString (self.color, combined_stones, (self.liberties | go_string.liberties) - combined_stones)

    @property
    def num_liberties(self):
        return len(self.liberties)

    def __eq__(self, other):
        return isinstance(other, GoString) and \
            self.color == other.color and \
            self.stones == other.stones and \
            self.liberties == other.liberties

class Board():
    def __init__(self, num_rows, num_cols):
        """ A board is initialized as an empty grid with the specified number
            of rows and columns
        """
        self.num_rows = num_rows
        self.num_cols = num_cols
        self._grid = {}
        self._hash = zobrist.EMPTY_BOARD

    def place_stone(self, player, point):
        """ Vs. the slow version, this uses the hash to speed this up. """
        assert self.is_on_grid(point) # is a valid point
        assert self._grid.get(point) is None # is empty
        adjacent_same_color = []
        adjacent_opposite_color = []
        liberties= []
        for neighbor in point.neighbors(): # examine direct neighbors
            if not self.is_on_grid(neighbor):
                continue
            neighbor_string = self._grid.get(neighbor)
            if neighbor_string is None:
                liberties.append(neighbor)
            elif neighbor_string.color == player:
                if neighbor_string not in adjacent_same_color:
                    adjacent_same_color.append(neighbor_string)
            else:
                if neighbor_string not in adjacent_opposite_color:
                    adjacent_opposite_color.append(neighbor_string)
        
        new_string = GoString(player, [point], liberties)

        # Merge any adjacent strings of the same color
        for same_color_string in adjacent_same_color:
            new_string = new_string.merged_with(same_color_string)
        for new_string_point in new_string.stones:
            self._grid[new_string_point] = new_string

        self._hash ^= zobrist.HASH_CODE[point, player] # apply hash

        # Reduce liberties of any adjacent strings of the opposite color
        for other_color_string in adjacent_opposite_color:
            replacement = other_color_string.without_liberty(point)
            if replacement.num_liberties:
                self._replace_string(other_color_string.without_liberty(point))
            else:
                self._remove_string(other_color_string) # opposite-color strings have 0 liberties, so remove them

    def is_on_grid(self, point):
        return 1 <= point.row <= self.num_rows and \
            1 <= point.col <= self.num_cols

    def get(self, point):
        """ Returns the content of a point on the board:
            a Player if a stone is on that point, else None
        """
        string = self._grid.get(point)
        if string is None:
            return None
        return string.color

    def get_go_string(self, point):
        """ Returns the entire string of stones at a point:
            a GoString if a stone is on that point, or else None
        """
        string = self._grid.get(point)
        if string is None:
            return None
        return string

    def _replace_string(self, new_string):
        """ Update Go board grid """
        for point in new_string.stones:
            self._grid[point] = new_string

    def _remove_string(self, string):
        """ Remove a string, then check if any new liberties are created. """
        for point in string.stones:
            for neighbor in point.neighbors():
                neighbor_string = self._grid.get(neighbor)
                if neighbor_string is None:
                    continue
                if neighbor_string is not string:
                    self._replace_string(neighbor_string.with_liberty(point))
            self._grid[point] = None

            self._hash ^= zobrist.HASH_CODE[point, string.color] # unapply the hash

    def zobrist_hash(self):
        return self._hash


class GameState():
    def __init__(self, board, next_player, previous, move):
        self.board = board
        self.next_player = next_player
        self.previous_state = previous
        if self.previous_state is None:
            self.previous_states = frozenset()
        else:
            self.previous_states = frozenset(
                previous.previous_states |
                { (previous.next_player, previous.board.zobrist_hash())}
            )
        self.last_move = move
    
    def apply_move(self, move):
        """ Returns the new GameState after applying the move """
        if move.is_play:
            next_board = copy.deepcopy(self.board)
            next_board.place_stone(self.next_player, move.point)
        else:
            next_board = self.board
        return GameState(next_board, self.next_player.other, self, move)

    @classmethod
    def new_game(cls, board_size):
        if isinstance(board_size, int):
            board_size = (board_size, board_size)
        board = Board(*board_size)
        return GameState(board, Player.black, None, None)

    def is_over(self):
        if self.last_move is None:
            return False
        if self.last_move.is_resign:
            return True
        second_last_move = self.previous_state.last_move
        if second_last_move is None:
            return False
        return self.last_move.is_pass and second_last_move.is_pass

    def is_move_self_capture(self, player, move):
        """ If the move is a play, ensure that there will be
            liberties after the move is complete.
        """
        if not move.is_play:
            return False
        next_board = copy.deepcopy(self.board)
        next_board.place_stone(player, move.point)
        new_string = next_board.get_go_string(move.point)
        return new_string.num_liberties == 0

    @property
    def situation(self):
        return (self.next_player, self.board)

    def does_move_violate_ko(self, player, move):
        """ Hashed previous states speed this up a lot
        """
        if not move.is_play:
            return False
        next_board = copy.deepcopy(self.board)
        next_board.place_stone(player, move.point)
        next_situation = (player.other, next_board.zobrist_hash())
        return next_situation in self.previous_states
    
    def is_valid_move (self, move):
        if self.is_over():
            return False
        if move.is_pass or move.is_resign:
            return True
        return (
            self.board.get(move.point) is None and
            not self.is_move_self_capture(self.next_player, move) and
            not self.does_move_violate_ko(self.next_player, move)
        )

# Stopped at 3.3 Ending a game