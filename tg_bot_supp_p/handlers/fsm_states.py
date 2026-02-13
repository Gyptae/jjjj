"""
FSM состояния для бота
"""
from aiogram.fsm.state import State, StatesGroup


class BroadcastStates(StatesGroup):
    """Состояния для рассылки"""
    waiting_for_message = State()


class ProductStates(StatesGroup):
    """Состояния для добавления товара"""
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_price = State()
    waiting_for_image = State()