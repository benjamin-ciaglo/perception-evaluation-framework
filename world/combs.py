"""."""
from itertools import combinations_with_replacement

def filter_combs(combs):
    """Filters combs with multiple types specced for feature."""
    final_combs = []
    for comb in combs:
        features = {'pitch', 'rate', 'intens'}
        keep = True
        for item in comb:
            split_item = item.split('-')
            item_feature, item_type = split_item[0], split_item[1]
            if item_feature in features and (item_type == 'sync' or item_type == 'prox'):
                features.remove(item_feature)
            else:
                keep = False
                break
        if keep:
            final_combs += [comb]
    print(final_combs)
    print(len(final_combs))

long_combs = list( \
    combinations_with_replacement( \
    ['intens-sync','intens-conver','intens-prox', \
    'pitch-sync','pitch-conver','pitch-prox', \
    'rate-sync','rate-conver','rate-prox'], \
    3))

mid_combs = list( \
    combinations_with_replacement( \
    ['intens-sync','intens-conver','intens-prox',\
    'pitch-sync','pitch-conver','pitch-prox',\
    'rate-sync','rate-conver','rate-prox'], \
    2))

filter_combs(long_combs)
filter_combs(mid_combs)
