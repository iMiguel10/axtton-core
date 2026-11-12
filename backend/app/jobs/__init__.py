"""Trabajos del worker (F5, arquitectura §8): funciones finas que llama SAQ.

Reciben solo ids, buscan con el planificador (`app/platform/scheduler.py`) lo que
cruza talleres y le pasan cada elemento a un service, que lo procesa en la
transacción de su taller. No deciden nada: lo deciden los services y `domain/`.
"""
