#!/bin/bash


function prepare() {
    BASE_IMAGE="cr.dataelem.com/dataelement/bisheng-backend:latest"
    docker run -itd --net=host -name bisheng-ie-dev -v $HOME:$HOME -v /public:/public $BASE_IMAGE bash

    # docker run -itd --net=host --name bisheng-ie-rt -v $HOME:$HOME -v /public:/public $BASE_IMAGE bash
    # docker exec bisheng-ie-rt mkdir -p /opt/bisheng-ie/
}

function commit_image() {
    docker rmi dataelement/bisheng-ie-rt:latest
    docker cp config.json bisheng-ie-rt:/opt/bisheng-ie/
    docker cp prompt.py bisheng-ie-rt:/opt/bisheng-ie/
    docker cp document_extract.py bisheng-ie-rt:/opt/bisheng-ie/
    docker cp run_web.py bisheng-ie-rt:/opt/bisheng-ie/
    docker cp scripts/entrypoint.sh bisheng-ie-rt:/opt/bisheng-ie/

    docker commit -m "bisheng ie image" lbisheng-ie-rt dataelement/bisheng-doc-ie:latest
    docker push dataelement/bisheng-doc-ie:latest
}

function test() {
    echo "test"
}

prepare
# commit_image
# test