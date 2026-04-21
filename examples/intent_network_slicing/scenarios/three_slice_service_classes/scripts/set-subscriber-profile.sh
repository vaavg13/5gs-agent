#!/bin/sh
# Update one subscriber's primary slice/DNN profile in MongoDB.

set -eu

IMSI="${1:?usage: set-subscriber-profile.sh IMSI SST SD DNN}"
SST="${2:?usage: set-subscriber-profile.sh IMSI SST SD DNN}"
SD="${3:?usage: set-subscriber-profile.sh IMSI SST SD DNN}"
DNN="${4:?usage: set-subscriber-profile.sh IMSI SST SD DNN}"

mongosh open5gs --quiet --eval "
const imsi = '${IMSI}';
const sst = Number('${SST}');
const sd = '${SD}';
const dnn = '${DNN}';
const coll = db.subscribers;
const subscriber = coll.findOne({ imsi });
if (!subscriber) {
  print(JSON.stringify({ error: 'subscriber_not_found', imsi }));
  quit(1);
}
coll.updateOne(
  { imsi },
  {
    \$set: {
      'slice.0.sst': sst,
      'slice.0.sd': sd,
      'slice.0.default_indicator': true,
      'slice.0.session.0.name': dnn,
      'slice.0.session.0.dnn': dnn
    }
  }
);
print(JSON.stringify({
  imsi,
  sst,
  sd,
  dnn
}));
"
