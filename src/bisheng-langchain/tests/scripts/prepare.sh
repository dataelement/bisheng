#!/bin/bash

function start_dev_container() {
  IMAGE="dataelement/bisheng-backend:v0.2.0"
  MOUNT="-v $HOME:$HOME -v /public:/public"
  docker run --net=host -itd --shm-size=1G \
    --name bisheng_langchain_dev ${MOUNT} $IMAGE bash
}

function update_contrainer() {
  echo "upadte"
  # docker exec bisheng_langchain_dev apt update && apt install -y vim
}


update_contrainer
# start_dev_container