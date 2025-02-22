import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from imports.utilities.data_management import *
from imports.evaluation.evaluation_measures import *
from imports.evaluation.calculate_aggregate_statistics import calculate_aggregate


def sigmoid(x):
    return math.exp(-np.logaddexp(0, -x))


def logistic(x, y):
    x_dot_y = np.dot(x, y)
    delta = sigmoid(x_dot_y)
    return delta


class HRM:

    def __init__(self, n_user, n_item, u_dim, v_dim, neg_samples=0,
                 n_epoch=4, alpha=0.01, lambda_r=0.001, decay=0.9, drop=0.5, n_thread=100, verbose=False):

        self.n_user = n_user
        self.n_item = n_item
        self.u_dim = u_dim
        self.v_dim = v_dim
        self.neg_samples = neg_samples
        self.n_epoch = n_epoch
        self.alpha = alpha
        self.lambda_r = lambda_r
        self.decay = decay
        self.drop = drop
        self.n_thread = n_thread
        self.verbose = verbose

        self.__state = 'initialized'

        self.map_user_item_set = None
        self.context_key_item_map = dict()
        self.lock = threading.Lock()

    def __get_context_maxpooling_and_droopout(self, basket, uid):

        context = np.zeros(self.v_dim)
        for item in basket:
            for d in range(self.v_dim):
                if self.V[item][d] > context[d]:
                    context[d] = self.V[item][d]
                    self.context_key_item_map[d] = '%s_i' % item

        # we randomly drop some items
        for d in range(self.v_dim):
            if random.random() > self.drop:
                context[d] = -10.0

        for d in range(self.u_dim):
            if self.U[uid][d] > context[d]:
                context[d] = self.U[uid][d]
                self.context_key_item_map[d] = '%s_u' % uid

        return context

    def __get_negative_items(self, uid):
        negative_items = list()
        items_bought = self.map_user_item_set[uid]
        total_step = 3000

        while len(negative_items) < self.neg_samples:
            total_step -= 1
            if total_step < 0:
                return negative_items
            neg_item = random.randint(0, self.n_item - 1)
            if neg_item not in items_bought:
                negative_items.append(neg_item)

        return negative_items

    def __get_negative_item_map(self, negative_items):
        negative_item_map = dict()
        for item in negative_items:
            item_neg = self.V[item, :]
            negative_item_map[item] = item_neg

        return negative_item_map

    def __get_neg_loss(self, negative_item_map, context):
        neg_loss_map = dict()
        for item in negative_item_map:
            f_neg = logistic(context, negative_item_map[item])
            neg_loss_map[item] = f_neg

        return neg_loss_map

    def __get_optimization_value(self, f, neg_loss_map):
        value = 0.0
        # for item in neg_loss_map:
        #     f_neg = math.log(1.0 - neg_loss_map[item])
        #     value += f_neg
        # value += math.log(f)

        for item in neg_loss_map:
            if 1.0 - neg_loss_map[item] > 0.0:
                f_neg = math.log(1.0 - neg_loss_map[item])
            else:
                f_neg = math.log(1.0 - 0.999999)
            value += f_neg

        value += math.log(f)
        return value

    def __update_rule(self, basket_with_context):
        uid = basket_with_context['uid']
        pitem = basket_with_context['pitem']
        basket = basket_with_context['basket']

        context = self.__get_context_maxpooling_and_droopout(basket, uid)
        item_predict = self.V[pitem, :]
        f = logistic(context, item_predict)

        delta_item_predict = context * (1.0 - f) * self.alpha
        new_item_predict = (delta_item_predict + item_predict) - item_predict * self.alpha * self.lambda_r

        negative_items = self.__get_negative_items(uid)
        negative_item_map = self.__get_negative_item_map(negative_items)
        neg_loss_map = self.__get_neg_loss(negative_item_map, context)
        value = self.__get_optimization_value(f, neg_loss_map)

        matrix_item_predict = item_predict
        delta_context_positive = matrix_item_predict * self.alpha * (1.0 - f)

        neg_new_vec_map = dict()
        for item in negative_item_map:
            item_neg = negative_item_map[item]
            f_neg = neg_loss_map[item]
            delta_item_neg = (context * -self.alpha * f_neg) - item_neg * self.lambda_r * self.alpha
            new_item_neg = delta_item_neg + item_neg
            matrix_item_neg = item_neg
            neg_new_vec_map[item] = new_item_neg
            delta_context_neg = matrix_item_neg * f_neg * self.alpha
            delta_context_positive -= delta_context_neg

        with self.lock:
            for d in range(len(new_item_predict)):
                self.V[pitem][d] = new_item_predict[d]

            for d in self.context_key_item_map:
                val = self.context_key_item_map[d]
                strs = val.split('_')
                if strs[1] == 'i':
                    item = int(strs[0])
                    item_val = self.V[item][d] + delta_context_positive[d] - self.V[item][
                        d] * self.lambda_r * self.alpha
                    self.V[item][d] = item_val
                elif strs[1] == 'u':
                    uid = int(strs[0])
                    user_val = self.U[uid][d] + delta_context_positive[d] - self.U[uid][d] * self.lambda_r * self.alpha
                    self.U[uid][d] = user_val

            for item in neg_new_vec_map:
                v = neg_new_vec_map[item]
                for d in range(len(v)):
                    self.V[item][d] = v[d]
        # print("Updated")
        return value

    def __get_user_bought_item_set(self, baskets):
        if self.map_user_item_set is None:
            self.map_user_item_set = list()
            for user_baskets in baskets:
                item_set = defaultdict(int)
                for basket in user_baskets:
                    for item in basket:
                        item_set[item] += 1

                self.map_user_item_set.append(item_set)

        return self.map_user_item_set

    def __get_user_tran_context(self, baskets):
        self.user_tran_context = list()
        for uid, user_baskets in enumerate(baskets):
            for bid in range(0, len(user_baskets)-1):
                basket = user_baskets[bid]

                bid_p1 = bid + 1
                for pitem in user_baskets[bid_p1]:
                    basket_with_context = {
                        'uid': uid,
                        'basket': basket,
                        'pitem': pitem
                    }
                    self.user_tran_context.append(basket_with_context)

        return self.user_tran_context

    def get_state(self):
        return self.__state

    def __init_matrices(self):
        self.U = (np.random.rand(self.n_user, self.u_dim) * 2.0 - 1.0) / self.u_dim
        self.V = (np.random.rand(self.n_item, self.v_dim) * 2.0 - 1.0) / self.v_dim

    def build_model(self, baskets):
        self.__state = 'built'
        self.__init_matrices()
        self.__get_user_bought_item_set(baskets)
        # self.__get_test_map_tran(baskets)
        self.__get_user_tran_context(baskets)
        # for a in self.user_tran_context:
        #     print a
        for i in range(self.n_epoch):
            print(i, range(self.n_epoch))
            random.shuffle(self.user_tran_context)
            value = 0.0

            with ThreadPoolExecutor(max_workers=self.n_thread) as executor:
                future_to_basket = {executor.submit(self.__update_rule, basket_with_context): basket_with_context
                                    for basket_with_context in self.user_tran_context}

                for future in as_completed(future_to_basket):
                    rule_value = future.result()
                    value += rule_value

            self.alpha *= self.decay
            if self.verbose:
                print(datetime.datetime.now(), 'Epoch %s, loss: %s' % (i, value))

        print("Built")
        return self

    def update_model(self, new_baskets):
        self.build_model(new_baskets)
        return self

    def __get_all_max_pooling_and_dropout(self, user_id, last_basket):
        context = np.zeros(self.v_dim)
        for item in last_basket:
            item_vec = self.V[item, :]
            for d in range(self.v_dim):
                if item_vec[d] > context[d]:
                    context[d] = item_vec[d]
        for d in range(self.u_dim):
            if context[d] < self.U[user_id][d]:
                context[d] = self.U[user_id][d]
        return context

    def predict(self, user_id, last_basket, pred_length=5):
        if self.__state != 'built':
            raise Exception('Model not built, prediction not available')

        vec_context = self.__get_all_max_pooling_and_dropout(user_id, last_basket)
        scores = np.dot(self.V, vec_context)
        item_rank = {k: v for k, v in enumerate(scores)}
        # print item_rank

        max_nbr_item = min(pred_length, len(item_rank))
        pred_basket = sorted(item_rank, key=item_rank.get, reverse=True)[:max_nbr_item]

        return pred_basket
