Transformation Layer
====================

The Transformation Layer maps raw database rows (from insert, update, or delete operations) into standard LangChain Document instances, manages unique document keys, and sanitizes input data.

Module Summary
--------------

.. autosummary::
   :nosignatures:

   ~pydebeziumai.transformation.document_builder.DocumentBuilder
   ~pydebeziumai.transformation.id_strategy.IdStrategy
   ~pydebeziumai.transformation.id_strategy.TablePkIdStrategy
   ~pydebeziumai.transformation.id_strategy.CompositeIdStrategy
   ~pydebeziumai.transformation.id_strategy.CustomIdStrategy
   ~pydebeziumai.transformation.projection_policy.ProjectionPolicy
   ~pydebeziumai.transformation.projection_policy.TableProjectionPolicy
   ~pydebeziumai.transformation.sanitizer.sanitize_metadata

API Reference
-------------

.. automodule:: pydebeziumai.transformation.document_builder
   :members:
   :show-inheritance:

.. automodule:: pydebeziumai.transformation.id_strategy
   :members:
   :show-inheritance:

.. automodule:: pydebeziumai.transformation.projection_policy
   :members:
   :show-inheritance:

.. automodule:: pydebeziumai.transformation.sanitizer
   :members:
   :show-inheritance:
