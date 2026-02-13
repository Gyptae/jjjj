"""
Общие состояния для всех хэндлеров
"""

# Словарь для отслеживания состояния пользователей (ожидают ли вопрос)
waiting_for_question = {}

# Словарь для хранения ID сообщений пользователей (для ответов админа)
user_messages = {}

# Словарь для отслеживания режима ответа админа {admin_id: user_id}
admin_reply_mode = {}

# Словарь для сбора медиа от админа {admin_id: [messages]}
admin_media_buffer = {}

control_messages = {}

broadcast_media_buffer = {}