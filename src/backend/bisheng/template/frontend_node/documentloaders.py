from typing import ClassVar, Dict, Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode


def build_file_field(suffixes: list,
                     fileTypes: list,
                     name: str = 'file_path',
                     fieldType='fileNode') -> TemplateField:
    """Build a template field for a document loader."""
    return TemplateField(
        field_type=fieldType,
        required=False,
        show=True,
        name=name,
        value='',
        suffixes=suffixes,
        fileTypes=fileTypes,
    )


class DocumentLoaderFrontNode(FrontendNode):

    def add_extra_base_classes(self) -> None:
        self.base_classes = ['Document']
        self.output_types = ['Document']

    file_path_templates: ClassVar[Dict] = {
        'ElemUnstructuredLoaderV0':
        build_file_field(
            suffixes=[
                '.html', '.md', '.txt', '.bmp', '.jpg', '.png', '.jpeg', '.doc', '.docx', '.pdf',
                '.ppt', '.pptx', '.xls', '.xlsx', '.tsv', '.csv', '.tiff'
            ],
            fileTypes=[
                'html',
                'md',
                'txt',
                'bmp',
                'jpg',
                'png',
                'jpeg',
                'doc',
                'docx',
                'pdf',
                'ppt',
                'pptx',
                '.xls',
                'xlsx',
                'tsv',
                'csv',
                'tiff',
            ],
        ),
        'AirbyteJSONLoader':
        build_file_field(suffixes=['.json'], fileTypes=['json']),
        'CoNLLULoader':
        build_file_field(suffixes=['.csv'], fileTypes=['csv']),
        'CSVLoader':
        build_file_field(suffixes=['.csv'], fileTypes=['csv']),
        'UnstructuredEmailLoader':
        build_file_field(suffixes=['.eml'], fileTypes=['eml']),
        'SlackDirectoryLoader':
        build_file_field(suffixes=['.zip'], fileTypes=['zip']),
        'EverNoteLoader':
        build_file_field(suffixes=['.xml'], fileTypes=['xml']),
        'FacebookChatLoader':
        build_file_field(suffixes=['.json'], fileTypes=['json']),
        'BSHTMLLoader':
        build_file_field(suffixes=['.html'], fileTypes=['html']),
        'UnstructuredHTMLLoader':
        build_file_field(suffixes=['.html'], fileTypes=['html']),
        'UnstructuredImageLoader':
        build_file_field(
            suffixes=['.jpg', '.jpeg', '.png', '.gif', '.bmp'],
            fileTypes=['jpg', 'jpeg', 'png', 'gif', 'bmp'],
        ),
        'UnstructuredMarkdownLoader':
        build_file_field(suffixes=['.md'], fileTypes=['md']),
        'PyPDFLoader':
        build_file_field(suffixes=['.pdf'], fileTypes=['pdf'], fieldType='fileNode'),
        'UnstructuredPowerPointLoader':
        build_file_field(suffixes=['.pptx', '.ppt'], fileTypes=['pptx', 'ppt']),
        'SRTLoader':
        build_file_field(suffixes=['.srt'], fileTypes=['srt']),
        'TelegramChatLoader':
        build_file_field(suffixes=['.json'], fileTypes=['json']),
        'TextLoader':
        build_file_field(suffixes=['.txt'], fileTypes=['txt']),
        'UnstructuredWordDocumentLoader':
        build_file_field(suffixes=['.docx', '.doc'], fileTypes=['docx', 'doc']),
        'PDFWithSemanticLoader':
        build_file_field(suffixes=['.pdf'], fileTypes=['pdf']),
        'UniversalKVLoader':
        build_file_field(
            suffixes=['.jpg', '.png', '.jpeg', '.bmp', '.pdf'],
            fileTypes=['jpg', 'png', 'jpeg', 'bmp', 'pdf'],
        ),
        'CustomKVLoader':
        build_file_field(
            suffixes=[
                '.jpg', '.png', '.jpeg', '.pdf', '.txt', '.docx', '.doc', '.bmp', '.tif', '.tiff',
                '.xls', '.xlsx'
            ],
            fileTypes=[
                'jpg', 'png', 'jpeg', 'pdf', 'txt', 'docx', 'doc', 'bmp', 'tif', 'tiff', 'xls',
                'xlsx'
            ],
        ),
    }

    def add_extra_fields(self) -> None:
        name = None
        display_name = 'Web Page'
        if self.template.type_name in {'PDFWithSemanticLoader'}:
            for field in build_pdf_semantic_loader_fields():
                self.template.add_field(field)
        if self.template.type_name in {'GitLoader'}:
            # Add fields repo_path, clone_url, branch and file_filter
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='repo_path',
                    value='',
                    display_name='Path to repository',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=False,
                    show=True,
                    name='clone_url',
                    value='',
                    display_name='Clone URL',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='branch',
                    value='',
                    display_name='Branch',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=False,
                    show=True,
                    name='file_filter',
                    value='',
                    display_name='File extensions (comma-separated)',
                    advanced=False,
                ))
        elif self.template.type_name in {'ElemUnstructuredLoaderV0'}:
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='unstructured_api_url',
                    value='',
                    display_name='unstructured_api_url',
                    advanced=False,
                ))
            self.template.add_field(self.file_path_templates[self.template.type_name])
        elif self.template.type_name in {'UniversalKVLoader'}:
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='ellm_model_url',
                    value='',
                    display_name='ellm_model_url',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='int',
                    required=False,
                    show=True,
                    name='max_pages',
                    value=30,
                    display_name='max_pages',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='schema',
                    value='',
                    display_name='schema',
                    advanced=False,
                ))
            self.template.add_field(self.file_path_templates[self.template.type_name])
        elif self.template.type_name in {'CustomKVLoader'}:
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='schemas',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='elm_api_base_url',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='elm_api_key',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='elem_server_id',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='task_type',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(field_type='int',
                              required=True,
                              show=True,
                              name='request_timeout',
                              advanced=True,
                              value=10))
            self.template.add_field(self.file_path_templates[self.template.type_name])
        elif self.template.type_name in self.file_path_templates:
            self.template.add_field(self.file_path_templates[self.template.type_name])
        elif self.template.type_name in {
                'WebBaseLoader',
                'AZLyricsLoader',
                'CollegeConfidentialLoader',
                'HNLoader',
                'IFixitLoader',
                'IMSDbLoader',
                'GutenbergLoader',
        }:
            name = 'web_path'
        elif self.template.type_name in {'GutenbergLoader'}:
            name = 'file_path'
        elif self.template.type_name in {'GitbookLoader'}:
            name = 'web_page'
        elif self.template.type_name in {
                'DirectoryLoader',
                'ReadTheDocsLoader',
                'NotionDirectoryLoader',
                'PyPDFDirectoryLoader',
        }:
            name = 'path'
            display_name = 'Local directory'
        if name:
            if self.template.type_name in {'DirectoryLoader'}:
                for field in build_directory_loader_fields():
                    self.template.add_field(field)
            else:
                self.template.add_field(
                    TemplateField(
                        field_type='str',
                        required=True,
                        show=True,
                        name=name,
                        value='',
                        display_name=display_name,
                    ))
            # add a metadata field of type dict
        self.template.add_field(
            TemplateField(
                field_type='code',
                required=True,
                show=True,
                name='metadata',
                value='{}',
                display_name='Metadata',
                multiline=False,
            ))

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        FrontendNode.format_field(field, name)
        if field.name == 'metadata':
            field.show = True
            field.advanced = False
        field.show = True
        if field.name == 'unstructured_api_url':
            field.show = True
            field.advanced = False
        if name == 'CustomKVLoader' and field.name == 'task_type':
            field.options = ['extraction-job', 'logic-job']
            field.value = 'logic-job'
        if name == 'CustomKVLoader' and field.name == 'schemas':
            field.field_type = 'str'
            field.info = "please use '|' seperate"
            field.is_list = False


def build_pdf_semantic_loader_fields():
    # file_path: str,
    #     password: Optional[Union[str, bytes]] = None,
    #     layout_api_key: str = None,
    #     layout_api_url: str = None,
    #     is_join_table: bool = True,
    #     with_columns: bool = False,
    #     support_rotate: bool = False,
    #     text_elem_sep: str = '\n',
    #     start: int = 0,
    #     n: int = None,
    #     verbose: bool = False
    file_path = TemplateField(field_type='file',
                              required=True,
                              show=True,
                              name='file_path',
                              value='',
                              display_name='pdf文件')
    password = TemplateField(field_type='str',
                             required=True,
                             show=True,
                             advanced=True,
                             name='password',
                             value=None,
                             display_name='password')
    layout_api_key = TemplateField(field_type='str',
                                   required=False,
                                   show=True,
                                   name='layout_api_key',
                                   value=None,
                                   display_name='layout_api_key')
    layout_api_url = TemplateField(field_type='str',
                                   required=False,
                                   show=True,
                                   name='layout_api_url',
                                   value=None,
                                   display_name='layout_api_url')
    is_join_table = TemplateField(field_type='bool',
                                  required=True,
                                  show=True,
                                  advanced=True,
                                  name='is_join_table',
                                  value='True',
                                  display_name='is_join_table')
    with_columns = TemplateField(field_type='bool',
                                 required=True,
                                 show=True,
                                 advanced=True,
                                 name='with_columns',
                                 value='False',
                                 display_name='with_columns')
    support_rotate = TemplateField(field_type='bool',
                                   required=True,
                                   show=True,
                                   advanced=True,
                                   name='support_rotate',
                                   value='False',
                                   display_name='support_rotate')
    text_elem_sep = TemplateField(field_type='str',
                                  required=True,
                                  show=True,
                                  advanced=True,
                                  name='text_elem_sep',
                                  value='\\n',
                                  display_name='text_elem_sep')
    start = TemplateField(field_type='int',
                          required=True,
                          show=True,
                          advanced=True,
                          name='start',
                          value=0,
                          display_name='start')
    n = TemplateField(field_type='int',
                      required=False,
                      show=True,
                      advanced=True,
                      name='n',
                      value=None,
                      display_name='n')
    verbose = TemplateField(field_type='bool',
                            required=True,
                            show=True,
                            advanced=True,
                            name='verbose',
                            value='False',
                            display_name='verbose')

    return (file_path, password, layout_api_key, layout_api_url, n, verbose, is_join_table,
            with_columns, support_rotate, text_elem_sep, start)


def build_directory_loader_fields():
    # if loader_kwargs is None:
    #         loader_kwargs = {}
    # self.path = path
    # self.glob = glob
    # self.load_hidden = load_hidden
    # self.loader_cls = loader_cls
    # self.loader_kwargs = loader_kwargs
    # self.silent_errors = silent_errors
    # self.recursive = recursive
    # self.show_progress = show_progress
    # self.use_multithreading = use_multithreading
    # self.max_concurrency = max_concurrency
    # Based on the above fields, we can build the following fields:
    # path, glob, load_hidden, silent_errors, recursive, show_progress, use_multithreading, max_concurrency
    # path
    path = TemplateField(
        field_type='str',
        required=True,
        show=True,
        name='path',
        value='',
        display_name='Local directory',
        advanced=False,
    )
    # glob
    glob = TemplateField(
        field_type='str',
        required=True,
        show=True,
        name='glob',
        value='**/*.txt',
        display_name='glob',
        advanced=False,
    )
    # load_hidden
    load_hidden = TemplateField(
        field_type='bool',
        required=False,
        show=True,
        name='load_hidden',
        value='False',
        display_name='Load hidden files',
        advanced=True,
    )
    # silent_errors
    silent_errors = TemplateField(
        field_type='bool',
        required=False,
        show=True,
        name='silent_errors',
        value='False',
        display_name='Silent errors',
        advanced=True,
    )
    # recursive
    recursive = TemplateField(
        field_type='bool',
        required=False,
        show=True,
        name='recursive',
        value='True',
        display_name='Recursive',
        advanced=True,
    )

    # use_multithreading
    use_multithreading = TemplateField(
        field_type='bool',
        required=False,
        show=True,
        name='use_multithreading',
        value='True',
        display_name='Use multithreading',
        advanced=True,
    )
    # max_concurrency
    max_concurrency = TemplateField(
        field_type='int',
        required=False,
        show=True,
        name='max_concurrency',
        value=10,
        display_name='Max concurrency',
        advanced=True,
    )

    return (
        path,
        glob,
        load_hidden,
        silent_errors,
        recursive,
        use_multithreading,
        max_concurrency,
    )
