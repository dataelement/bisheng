from bisheng.core.context import get_context
from bisheng.core.search.elasticsearch.manager import statistics_es_name, EsConnManager
from datetime import datetime


class TelemetryService:
    """
    Service for collecting and sending telemetry data about business operations to a data store.
    """

    def __init__(self):
        self.es_manager: EsConnManager = get_context().get(statistics_es_name)

    async def capture(self, event_type: str, event_data: dict, index_name: str = "bisheng_telemetry_events"):
        """
        Captures a telemetry event and sends it to Elasticsearch.

        :param event_type: The type of the event (e.g., 'user_login', 'create_flow').
        :param event_data: A dictionary containing the event details.
        :param index_name: The Elasticsearch index to log the event to.
        """
        if not self.es_manager or not self.es_manager.client:
            # TODO: Replace with a more robust logging mechanism
            print(f"TelemetryService: Elasticsearch manager not available. Event '{event_type}' not captured.")
            return

        document = {
            "event_type": event_type,
            "timestamp": datetime.utcnow(),
            "data": event_data,
        }

        try:
            await self.es_manager.client.index(index=index_name, document=document)
        except Exception as e:
            # TODO: Replace with a more robust logging mechanism
            print(f"TelemetryService: Error capturing event to Elasticsearch: {e}")


telemetry_service = TelemetryService()
