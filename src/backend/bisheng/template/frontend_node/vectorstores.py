from typing import List, Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode


class VectorStoreFrontendNode(FrontendNode):

    def add_extra_fields(self) -> None:
        extra_fields: List[TemplateField] = []
        # Add search_kwargs field
        extra_field = TemplateField(
            name='search_kwargs',
            field_type='code',
            required=False,
            placeholder='',
            show=True,
            advanced=True,
            multiline=False,
            value='{}',
        )
        extra_field2 = TemplateField(
            name='search_type',
            field_type='str',
            required=False,
            placeholder='',
            value='similarity',
        )
        extra_fields.append(extra_field2)
        extra_fields.append(extra_field)

        if self.template.type_name == 'Weaviate':
            extra_field = TemplateField(
                name='weaviate_url',
                field_type='str',
                required=True,
                placeholder='http://localhost:8080',
                show=True,
                advanced=False,
                multiline=False,
                value='http://localhost:8080',
            )
            # Add client_kwargs field
            extra_field2 = TemplateField(
                name='client_kwargs',
                field_type='code',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                value='{}',
            )
            extra_fields.extend((extra_field, extra_field2))

        elif self.template.type_name == 'Chroma':
            # New bool field for persist parameter
            extra_field = TemplateField(
                name='persist',
                field_type='bool',
                required=False,
                show=True,
                advanced=False,
                value=False,
                display_name='Persist',
            )
            extra_fields.append(extra_field)
        elif self.template.type_name == 'Pinecone':
            # add pinecone_api_key and pinecone_env
            extra_field = TemplateField(
                name='pinecone_api_key',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                password=True,
                value='',
            )
            extra_field2 = TemplateField(
                name='pinecone_env',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                value='',
            )
            extra_fields.extend((extra_field, extra_field2))
        elif self.template.type_name == 'FAISS':
            extra_field = TemplateField(
                name='folder_path',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                display_name='Local Path',
                value='',
            )
            extra_field2 = TemplateField(
                name='index_name',
                field_type='str',
                required=False,
                show=True,
                advanced=False,
                value='',
                display_name='Index Name',
            )
            extra_fields.extend((extra_field, extra_field2))
        elif self.template.type_name == 'SupabaseVectorStore':
            self.display_name = 'Supabase'
            # Add table_name and query_name
            extra_field = TemplateField(
                name='table_name',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                value='',
            )
            extra_field2 = TemplateField(
                name='query_name',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                value='',
            )
            # Add supabase_url and supabase_service_key
            extra_field3 = TemplateField(
                name='supabase_url',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                value='',
            )
            extra_field4 = TemplateField(
                name='supabase_service_key',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                password=True,
                value='',
            )
            extra_fields.extend((extra_field, extra_field2, extra_field3, extra_field4))

        elif self.template.type_name == 'MongoDBAtlasVectorSearch':
            self.display_name = 'MongoDB Atlas'

            extra_field = TemplateField(
                name='mongodb_atlas_cluster_uri',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                display_name='MongoDB Atlas Cluster URI',
                value='',
            )
            extra_field2 = TemplateField(
                name='collection_name',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                display_name='Collection Name',
                value='',
            )
            extra_field3 = TemplateField(
                name='db_name',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                display_name='Database Name',
                value='',
            )
            extra_field4 = TemplateField(
                name='index_name',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=True,
                multiline=False,
                display_name='Index Name',
                value='',
            )
            extra_fields.extend((extra_field, extra_field2, extra_field3, extra_field4))

        elif self.template.type_name == 'ElasticKeywordsSearch':
            extra_field = TemplateField(
                name='elasticsearch_url',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=False,
                multiline=False,
                display_name='ES_connection_url',
                value='',
            )
            extra_field2 = TemplateField(
                name='ssl_verify',
                field_type='str',
                required=False,
                placeholder='',
                show=True,
                advanced=False,
                multiline=False,
                display_name='ssl_verify',
                value='',
            )
            extra_field3 = TemplateField(
                name='llm',
                field_type='BaseLLM',
                required=False,
                show=True,
                advanced=False,
                display_name='LLM',
            )
            extra_field4 = TemplateField(
                name='prompt',
                field_type='BasePromptTemplate',
                required=False,
                show=True,
                advanced=False,
                display_name='prompt',
            )
            extra_fields.extend((extra_field, extra_field2, extra_field3, extra_field4))

        elif self.template.type_name == 'ElasticsearchStore':
            extra_fields.append(
                TemplateField(
                    name='embedding',
                    field_type='str',
                    required=False,
                    placeholder='',
                    show=True,
                    advanced=False,
                    multiline=False,
                    value='',
                ))
            extra_fields.append(
                TemplateField(
                    name='connect_kwargs',
                    field_type='dict',
                    required=True,
                    show=True,
                    advanced=False,
                    multiline=False,
                    value={
                        'es_url': 'http://bisheng-es:9200',
                        'es_user': 'elastic',
                        'es_password': ''
                    },
                ))
            extra_fields.append(
                TemplateField(name='index_name',
                              field_type='str',
                              required=False,
                              show=True,
                              advanced=False,
                              multiline=False))

        if extra_fields:
            for field in extra_fields:
                self.template.add_field(field)

    def add_extra_base_classes(self) -> None:
        self.base_classes.extend(('BaseRetriever', 'VectorStoreRetriever'))
        if self.name == 'ElasticsearchWithPermissionCheck':
            self.base_classes.append('ElasticKeywordsSearch')

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        FrontendNode.format_field(field, name)
        # Define common field attributes
        basic_fields = [
            'work_dir', 'collection_name', 'api_key', 'location', 'persist_directory', 'persist',
            'weaviate_url', 'index_name', 'namespace', 'folder_path', 'table_name', 'query_name',
            'supabase_url', 'supabase_service_key', 'mongodb_atlas_cluster_uri', 'collection_name',
            'db_name', 'ssl_verify', 'elasticsearch_url', 'llm', 'prompt', 'connect_kwargs'
        ]
        advanced_fields = [
            'n_dim', 'key', 'prefix', 'distance_func', 'content_payload_key',
            'metadata_payload_key', 'timeout', 'host', 'path', 'url', 'port', 'https',
            'prefer_grpc', 'grpc_port', 'pinecone_api_key', 'pinecone_env', 'client_kwargs',
            'search_kwargs', 'search_type'
        ]

        # Check and set field attributes
        if field.name == 'texts':
            # if field.name is "texts" it has to be replaced
            # when instantiating the vectorstores
            field.name = 'documents'

            field.field_type = 'Document'
            field.display_name = 'Documents'
            field.required = False
            field.show = True
            field.advanced = False
            if name == 'MilvusWithPermissionCheck' or name == 'ElasticsearchWithPermissionCheck':
                field.show = False
                field.advanced = True

        elif 'embedding' in field.name:
            # for backwards compatibility
            field.name = 'embedding'
            field.required = True
            field.show = True
            field.advanced = False
            field.display_name = 'Embedding'
            field.field_type = 'Embeddings'
            if name == 'ElasticKeywordsSearch':
                field.show = False
                field.required = False
            elif name in ['MilvusWithPermissionCheck', 'ElasticsearchWithPermissionCheck']:
                field.advanced = True
                field.show = False
                field.required = False

        elif field.name == 'collection_name':
            field.show = True
            field.advanced = False
            field.value = ''
            field.field_type = 'knowledge_one'  # 知识库单选类型，前端渲染单选列表
            if name == 'MilvusWithPermissionCheck':
                field.is_list = True
                field.field_type = 'knowledge_list'  # 知识库多选类型，前端渲染多选列表
                field.required = True
        elif field.name == 'index_name':
            field.show = True
            field.advanced = False
            field.value = ''
            field.field_type = 'knowledge_one'
            if name == 'ElasticsearchWithPermissionCheck':
                field.is_list = True
                field.field_type = 'knowledge_list'  # 知识库多选类型，前端渲染多选列表
                field.required = True

        elif field.name in basic_fields:
            field.show = True
            field.advanced = False
            if field.name == 'api_key':
                field.display_name = 'API Key'
                field.password = True
            elif field.name == 'location':
                field.value = ':memory:'
                field.placeholder = ':memory:'

        elif field.name in advanced_fields:
            field.show = True
            field.advanced = True
            if 'key' in field.name:
                field.password = False

        elif field.name == 'text_key':
            field.show = False

        elif field.name == 'connection_args':
            field.show = True
            field.advanced = False
            field.value = ''
            if name in ['MilvusWithPermissionCheck', 'ElasticsearchWithPermissionCheck']:
                field.show = False
                field.advanced = True
