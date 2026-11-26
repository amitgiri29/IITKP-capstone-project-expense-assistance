#!/usr/bin/env bash
# macOS: double-click this file in Finder to set up and start the app.
# The first time, macOS may block it: right-click the file, choose Open, then Open again.
cd "$(dirname "$0")" || exit 1
bash ./setup.sh "$@"
status=$?
if [ $status -ne 0 ]; then
  echo
  read -r -p "Setup did not finish (see the message above). Press Enter to close this window." _
fi
exit $status
