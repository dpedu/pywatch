#!/bin/sh

if [ ! -d testenv ] ; then
    virtualenv --python=python3.4 testenv
    source testenv/bin/activate
    pip3 install -r requirements.txt
    deactivate
fi

source testenv/bin/activate
./watch.py ~/PhpstormProjects/pronq/obt_prototypes/ -u root -p vagrant -s localdev.saas.hp.com \
    --map "server/cms:/var/www/drupal" \
    --map "shared-assets:/var/www/drupal/sites/all/themes/zen_pronq_mktg/shared-assets" \
    --map ":/root"
