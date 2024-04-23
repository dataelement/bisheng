#!/bin/bash


function prepare() {
    BASE_IMAGE="cr.dataelem.com/dataelement/bisheng-backend:latest"
    # docker run -itd --net=host --name bisheng-ie-dev -v $HOME:$HOME -v /public:/public $BASE_IMAGE bash
    # docker exec bisheng-ie-dev pip3 install -r $HOME/projects/bisheng/src/bisheng-langchain/experimental/document_ie_v2/scripts/requirements.txt

    # docker run -itd --net=host --name bisheng-ie-rt -v $HOME:$HOME -v /public:/public $BASE_IMAGE bash
    # docker exec bisheng-ie-rt mkdir -p /opt/bisheng-ie/
    # docker exec bisheng-ie-rt pip3 install -r $HOME/projects/bisheng/src/bisheng-langchain/experimental/document_ie_v2/scripts/requirements.txt
    docker exec bisheng-ie-rt pip3 install loguru
}

function commit_image() {
    new_image="cr.dataelem.com/dataelement/bisheng-doc-ie:latest"
    docker rmi ${new_image} || echo "escaped"
    docker cp config.json bisheng-ie-rt:/opt/bisheng-ie/
    docker cp prompt.py bisheng-ie-rt:/opt/bisheng-ie/
    docker cp document_extract.py bisheng-ie-rt:/opt/bisheng-ie/
    docker cp llm_extract.py bisheng-ie-rt:/opt/bisheng-ie/
    docker cp run_web.py bisheng-ie-rt:/opt/bisheng-ie/
    docker cp ie_client.py bisheng-ie-rt:/opt/bisheng-ie/
    docker cp scripts/entrypoint.sh bisheng-ie-rt:/opt/bisheng-ie/

    docker commit -m "bisheng ie v2 image" bisheng-ie-rt ${new_image}
    docker push ${new_image}
}

function test() {
    echo "test"
    docker run --net=host -itd --name bisheng-docie cr.dataelem.com/dataelement/bisheng-doc-ie:latest bash /opt/bisheng-ie/entrypoint.sh
}   

# prepare
commit_image
# test