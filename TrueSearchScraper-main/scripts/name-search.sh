#!/bin/bash

set -x

SHEET_ID="$1"
SHEET_NAME="$2"
WORKER_QUEUE="$3"

yarn start:name-search $SHEET_ID $SHEET_NAME $WORKER_QUEUE
