#!/bin/bash


function prepare() {
    BASE_IMAGE="cr.dataelem.com/dataelement/bisheng-backend:latest"
    CONTAINER_NAME=bisheng-ie-v3
    docker rm -f $CONTAINER_NAME
    docker run -itd --net=host --name $CONTAINER_NAME  -v /public:/public --gpus 'all' $BASE_IMAGE bash
    docker exec $CONTAINER_NAME mkdir -p /opt/bisheng-ie/
    docker exec $CONTAINER_NAME apt-get install vim tmux

    docker exec $CONTAINER_NAME \
    pip3 install \
    -r /public/youjiachen/bisheng/src/bisheng-langchain/experimental/document_ie_v3/scripts/requirements.txt

    docker exec $CONTAINER_NAME pip3 install torch==2.0.1+cu117 -f https://mirror.sjtu.edu.cn/pytorch-wheels/torch_stable.html
}

function commit_image() {
    BUILD_IAMGE="bisheng-ie-v3:latest"
    CONTAINER_NAME=bisheng-ie-v3
    docker rmi ${BUILD_IAMGE} || echo "escaped"
    docker cp config.yaml $CONTAINER_NAME:/opt/bisheng-ie/
    docker cp prompt.py $CONTAINER_NAME:/opt/bisheng-ie/
    docker cp document_extract.py $CONTAINER_NAME:/opt/bisheng-ie/
    docker cp llm_extract.py $CONTAINER_NAME:/opt/bisheng-ie/
    docker cp run_web.py $CONTAINER_NAME:/opt/bisheng-ie/
    docker cp scripts/entrypoint.sh $CONTAINER_NAME:/opt/bisheng-ie/
    docker cp utils.py $CONTAINER_NAME:/opt/bisheng-ie/

    docker commit -m "bisheng ie v3 image" $CONTAINER_NAME $BUILD_IAMGE
    # docker push ${new_image}
}

function _test() {
    echo "test"
    BUILD_IAMGE="bisheng-ie-v3:latest"
    TEST_CONTAINER_NAME=test_doc_ie
    docker rm -f $TEST_CONTAINER_NAME
    docker run --net=host -itd --name $TEST_CONTAINER_NAME  -v /public:/public --gpus 'all' $BUILD_IAMGE bash 
    docker exec $TEST_CONTAINER_NAME bash /opt/bisheng-ie/entrypoint.sh
}   

# prepare
# commit_image
_test