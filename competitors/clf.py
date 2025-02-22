import math
import datetime
import numpy as np

from sklearn.tree import DecisionTreeClassifier

from forgotten_items.imports.utilities.data_management import *
from forgotten_items.imports.evaluation.evaluation_measures import *
from forgotten_items.imports.evaluation.calculate_aggregate_statistics import calculate_aggregate


def get_bin_id(days_since_last_bought):
    bin_id = int(days_since_last_bought) // 5
    return min(bin_id, 10)


def sigmoid(x):
    return math.exp(-np.logaddexp(0, -x))


class CLF:

    def __init__(self, min_item_occurrences=1):

        self.__state = 'initialized'
        self.min_item_occurrences = min_item_occurrences

        self.item_clf = None
        self.item_last_basket_features = None
        self.last_basket = None

    def get_state(self):
        return self.__state

    def build_model(self, baskets):
        self.__state = 'built'

        sorted_basket_ids = sorted(baskets['data'])

        items_shop_features = dict()
        items_date_last_purchase = dict()
        items_count_purchases = dict()
        items_freq_histogram = dict()

        # calculates temporal features for each item
        for basket_id in sorted_basket_ids:
            date_object = datetime.datetime.strptime(basket_id[0:10], '%Y_%m_%d')

            basket = baskets['data'][basket_id]['basket'].keys()
            for item in items_shop_features:
                days_since_last_bought = 1.0 * (date_object - items_date_last_purchase[item]).days
                dow = date_object.weekday()
                hour = date_object.hour / 6
                month = date_object.month
                quarter = (month / 4) + 1

                item_purchased = 0
                if item in basket:
                    item_purchased = 1
                    items_count_purchases[item] += 1
                    items_date_last_purchase[item] = date_object

                    bin_id = get_bin_id(days_since_last_bought)
                    bin_id = int(bin_id)  # Ensure bin_id is an integer
                    items_freq_histogram[bin_id] += 1.0

                bin_id = get_bin_id(days_since_last_bought)
                bin_id = int(bin_id)  # Ensure bin_id is an integer
                frequency_of_interval = items_freq_histogram[bin_id] / items_count_purchases[item]

                min1_trans = [0, 0, 0, 0, 0, 0, 0]
                min2_trans = [0, 0, 0, 0, 0, 0, 0]
                min3_trans = [0, 0, 0, 0, 0, 0, 0]
                min4_trans = [0, 0, 0, 0, 0, 0, 0]

                if len(items_shop_features[item]) > 0:
                    min1_trans = items_shop_features[item][-1][:7]
                if len(items_shop_features[item]) > 1:
                    min2_trans = items_shop_features[item][-2][:7]
                if len(items_shop_features[item]) > 2:
                    min3_trans = items_shop_features[item][-3][:7]
                if len(items_shop_features[item]) > 3:
                    min4_trans = items_shop_features[item][-4][:7]

                item_basket_features = [days_since_last_bought,
                                        frequency_of_interval,
                                        bin_id,
                                        dow,
                                        hour,
                                        month,
                                        quarter]

                item_basket_features.extend(min1_trans)
                item_basket_features.extend(min2_trans)
                item_basket_features.extend(min3_trans)
                item_basket_features.extend(min4_trans)

                # da mettere se si usa un linear classifier tipo perceptron
                # non_linear_combinations = list()
                # for i in xrange(7):
                #     values = list()
                #     for j in xrange(5):
                #         values.append(item_basket_features[i + j * 7])
                #     if i < 2:
                #         non_linear_combinations.append(sigmoid(np.sum(values)))
                #     else:
                #         val = 1.0
                #         for j in xrange(4):
                #             if values[j] != values[j + 1]:
                #                 val = 0.0
                #                 break
                #         non_linear_combinations.append(val)
                #
                # item_basket_features.extend(non_linear_combinations)

                item_basket_features.extend([item_purchased])

                items_shop_features[item].append(item_basket_features)

            for item in basket:
                if item not in items_shop_features:
                    items_shop_features[item] = list()
                    items_date_last_purchase[item] = date_object
                    items_count_purchases[item] = 1
                    items_freq_histogram = {
                        0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0,
                        6: 0.0, 7: 0.0, 8: 0.0, 9: 0.0, 10: 0.0
                    }

        self.last_basket = baskets['data'][sorted_basket_ids[-1]]['basket'].keys()
        self.item_clf = dict()
        self.item_last_basket_features = dict()

        # train classifier for each item
        for item in items_shop_features:
            X_train = list()
            Y_train = list()

            for features in items_shop_features[item]:
                # X_train.append(features[:-1]) caso perceptron
                X_train.append(features[:-7])
                Y_train.append(features[-1])

            if np.sum(Y_train) <= self.min_item_occurrences - 1:
                continue

            clf = DecisionTreeClassifier(criterion='gini', splitter='best', max_depth=None,
                                         min_samples_split=20, min_samples_leaf=10,
                                         min_weight_fraction_leaf=0.0, max_features=None,
                                         random_state=None, max_leaf_nodes=None,
                                         min_impurity_decrease=0.0, class_weight=None)

            clf.fit(X_train, Y_train)
            self.item_clf[item] = clf
            self.item_last_basket_features[item] = np.reshape(X_train[-1], (1, -1))

        return self

    def update(self, new_baskets):
        if self.__state != 'built':
            raise Exception('Model not built, cannot be updated')
        return self.build_model(new_baskets)

    def predict(self, pred_length=5):
        if self.__state != 'built':
            raise Exception('Model not built, prediction not available')

        item_score = dict()
        for item in self.item_clf:
            clf = self.item_clf[item]
            prediction = clf.predict_proba(self.item_last_basket_features[item])
            if len(prediction[0]) == 1:
                will_be_purchased = clf.predict(self.item_last_basket_features[item])[0]
                if will_be_purchased == 1:
                    item_score[item] = 1.0
                else:
                    item_score[item] = 0.0
            else:
                item_score[item] = prediction[0][1]

        if len(item_score) > 0:
            max_nbr_item = min(pred_length, len(item_score))
            pred_basket = sorted(item_score, key=item_score.get, reverse=True)[:max_nbr_item]
        else:
            pred_basket = self.last_basket

        return pred_basket
