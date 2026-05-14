# 文件解析pipeline流程说明

## 1. 使用loader加载文件内容到内存中

loader的作用是将文件内容加载到内存中，供后续的文本处理和向量化使用。常见的loader有以下几种：

- `TextLoader`：用于加载纯文本文件。
- `ExcelLoader`：用于加载excel文件。
- 等等...

## 2. 使用transformer对文本进行处理

transformer的作用是对加载的文本进行处理，提取出有用的信息，常见的transformer有以下几种：

- `TextSplitter`：用于将文本分割成更小的片段
- `abstractor`：用于对文本进行摘要提取
- `extra_file`：用于把原始文本内的图片或者对应的预览文件持久化落盘
- 等等...

## 3. 使用vector将文本插入到向量数据库中

vector的作用是将处理后的文本进行向量化，并插入到向量数据库中，常见的vector有以下几种：

- `MilvusVector`：用于将文本插入到Pinecone向量数据库中。
- `EsVector`：用于将文本插入到Weaviate向量数据库中。
- 等等...

# 业务流程说明

## 业务主要是根据业务需求来组合不同的loader、transformer和vector来实现不同的功能。例如：

- 如果需要将文本文件中的内容进行摘要提取并插入到向量数据库中，可以使用`TextLoader`加载文本文件，使用`abstractor`
  进行摘要提取，最后使用`MilvusVector`将摘要插入到milvus向量数据库中

