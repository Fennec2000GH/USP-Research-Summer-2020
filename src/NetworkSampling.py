
from __future__ import annotations
from littleballoffur.exploration_sampling import (RandomWalkSampler,
                                                commonneighborawarerandomwalksampler,
                                                SnowBallSampler,
                                                CommunityStructureExpansionSampler,
                                                FrontierSampler)
import copy
from inspect import signature
import itertools
from joblib import Parallel, delayed
import matplotlib.pyplot as plt
import multiprocessing as mp
import networkx as nx
import numpy as np
import param
import pandas as pd
# import pdb
# pdb.disable()
from typing import *

# NS = Network Sampling
class NSMethod(NamedTuple):
    """Convenient container to hold any function and its parameters as a dict separately, facilitating destructuring later.

    Args:
        func (Callable): A callable that takes in at least 1 parameter
        params (Dict[str, Any]): Specific parameter values as a dict
    """
    func: Callable
    params: Dict[str, Any]

#region
class NetworkSampler:
    """Light-weight, high-level framework used to sample networks with a given algorithm and evalutate the sample according to a given metric."""
    # METHODS
    def __init__(self, sampler: Any, scorer: NSMethod) -> None:
        """
        Initializes the smapling algorithm and evalutation metric.

        Args:
            sampler (Any): Either a sampler instance from littleballoffur library or a custom-made instance with compatible structure
            scorer (NSMethod): Function and parameters of scoring metric to evaluate network sample

        Returns:
            None: Does not return anything
        """
        # pdb.set_trace(header='NetworkSampler - __init__ - Initializing sampler and scorer')
        if(not hasattr(sampler, 'sample')):
            raise ValueError('Sampler does not have a \'sample\' callable')

        self.sampler = sampler
        self.scorer = scorer
        self.prev_sample = None
        if __debug__:
            print(f'sampler: {self.sampler}')
            print(f'scorer: {self.scorer}')

    #ACCESSORS
#region
    # @property
    # def sampler(self):
    #     """
    #     Gets current sampler object

    #     Returns:
    #         Any: Returns currently used sampler object
    #     """
    #     return self.sampler
#endregion

    # @sampler.setter
    def set_sampler(self, new_sampler: Any):
        """
        Resets sampler object.

        Args:
            new_sampler (Any): New sampler object to replace current sampler

        Raises:
            ValueError: New sampler object lacks 'sample' method or the 'sample' method lacks the paramters ['graph', 'start_node']

        Returns:
            None: None
        """
        if not hasattr(new_sampler, 'sample'):
            raise ValueError('Sampler object must have \'sample\' method.')
        _sample = getattr(new_sampler, 'sample')
        sig = signature(_sample)
        if 'graph' not in sig.parameters:
            raise ValueError('\'graph\' is not a parameter in \'sample\' method of new sampler')
        if 'start_node' not in sig.parameters:
            raise ValueError('\'start_node\' is not a parameter in \'sample\' method of new sampler')

        self.sampler = new_sampler

#region
    # @property
    # def scorer(self):
    #     """
    #     Gets current scorer object.

    #     Returns:
    #         NSMethod: Returns currently used scoring metric and its parameters
    #     """
    #     return self.scorer
#endregion

    def set_scorer(self, new_scorer: NSMethod):
        """
        Resets scorer object.

        Args:
            new_scorer (NSMethod): New scorer object to replace current scorer.

        Raises:
            TypeError: new_scorer is not of type NSMethod
            ValueError: 'graph'  is not a parameter in specific method for scoring

        Returns:
            None: None
        """
        if type(new_scorer) != NSMethod:
            raise TypeError('New scorer object is not of type NSMethod')
        sig = signature(new_scorer.func)
        if 'graph' not in sig.parameters:
            raise ValueError('\'graph\' is not a parameter in specific method for scoring')

        self.scorer = new_scorer

    # MUTATORS
    def sample(self, graph: nx.Graph, start_node: int=None) -> nx.Graph:
        """
        Extracts subgraph from network by applying given sampling algorithm and parameters if provided.

        Args:
            graph (nx.Graph): Original graph or network to sample from
            start_node (int, optional): Node where sampling starts to spread. Defaults to None.

        Returns:
            nx.Graph: Sampled network.
        """
        # pdb.set_trace(header='NetworkSampler - sample - Entering sample')
        if __debug__:
            print('sampler attributes:\n')
            print(dir(self.sampler))

        _sample = getattr(self.sampler, 'sample')
        if __debug__:
            print('_sample attributes:\n')
            print(dir(_sample))
            sig = signature(_sample)
            print(f'_sample signature: {sig}')
            print(f'_sample parameters: {sig.parameters}')
            print(f'_sample_return_annotation: {sig.return_annotation}')

        self.prev_sample = self.sampler.sample(graph=graph, start_node=start_node)
        return self.prev_sample

    def score(self):
        """Evaluates the sample network by the provided metric. Calling the 'sample' method must be done first before calling 'score'.

        Returns:
            float: Evaluation score using given scoring metric
        """
        # pdb.set_trace(header='NetworkSampler - score - Entering score')
        if self.prev_sample is None:
            raise ValueError('No calls to \'sample\' method has been made yet.')

        score_func, score_params = self.scorer.func, self.scorer.params
        return score_func(graph=self.prev_sample, **score_params)

    def sample_and_score(self, graph: nx.Graph, start_node: int=None):
        """Scores network sampling algorithm with a fresh sample each time by automatically calling 'sample' first.

        Args:
            graph (nx.Graph): Network to sample from.
            start_node (int, optional): Node where sampling starts to spread. Defaults to None.

        Returns:
            Tuple[float, nx.Graph]: Tuple of score and corresponding sample of network.
        """
        # pdb.set_trace(header='NetworkSampler - sample_and_score - Entering sample_and_score')
        sample_result = self.sampler.sample(graph=graph, start_node=start_node)
        score_result = score()

        if __debug__:
            print(f'sample_result: {sample_result}')
            print(f'score_result: {score_result}')

        return sample_result, score_result
#endregion

def _rescore(ns: NetworkSampler, graph: nx.Graph, start_node: int=None):
    """
    Helper function does a re-sampling followed by an immediate re-scoring is completed.

    Args:
        ns (NetworkSampler): Network sampler to use
        graph (nx.Graph): Network to sample from
        start_node (int, optional): Starting node. Defaults to None.
    """
    ns.sample(graph, start_node)
    return ns.score()

#region
class NetworkSamplerTuner:
    """
    Takes a given NetworkSampler object and tunes chosen parameters. Each set of parameter values for testing can either be a bounded interval,
    which undergoes the bisection method, or a select iterable of test values to scan across.
    """
    def __init__(self, nssampler: NetworkSampler, graph: nx.Graph, start_node: int):
        """
        Initializes a parameter tuning framework to test on a given netowrk and start node.

        Args:
            nssampler (NetworkSampler): NetworkSampler object to tune
            graph (nx.Graph): Network to test on; this should be the same network intended to sample from
            start_node (int): Node where sampling starts to spread
        """

        self.nssampler = nssampler
        self.graph = graph
        self.start_node = start_node

    def tune_single(self, param_name: str, param_values: Union[Iterable[float], Tuple[float, float]], int_only: bool=False, n_trials: int=1, n_iter: int=10, n_no_improve: int=None):
        """
        Tunes a single parameter for a sampler. This assumes all other required parameters are already fixed in __init__ of sampler.

        Args:
            param_name (str): Name of parameter to tune
            param_values (Union[Iterable[float], Tuple[float, float]]): Either a list of discretevalues or a bounded interval (2-element tuple)
                for the bisection method.
            int_only (bool, optional): Whether only integer values are accepted for the parameter. Defaults to False.
            n_trials (int, optional): Number of trials to commit for each tested parameter value. The score for that parameter value is the
                mean over all 'n_trials' trials. Defaults to 1.
            n_iter (int, optional): Number of iterations to use before stopping; only applies to biseciotn method 'param_values' is a tuple.
                Defaults to 10.
            n_no_improve (int, optional): Number of iterations without improvement on best score to confirm stopping. Defaults to None.

        Returns:
            Union[int, float]: Parameter value that yielded highest score within given constraints of tuner.
        """
        sig = signature(self.nssampler.sampler.__init__)
        if param_name not in sig.parameters:
            raise ValueError(f'parameter {param_name} is not in __init__ method of sampler {self.sampler}')

        # Variables common to different constraints
        pool = mp.Pool(processes=mp.cpu_count())
        score_list = list()  # Temporarily holds scores for the same parameter value over n_trials
        no_improve_cnt = 0
        high_score = 0
        best_param_value = None

        # Use bisection method on bounded itnerval
        if type(param_values) == tuple:
            lower_bound = param_values[0]
            upper_bound = param_values[1]
            mid = (lower_bound + upper_bound) / 2.0
            if int_only:
                mid = int(mid)

            for iter_cnt in np.arange(1, n_iter):
                print(f'iter_cnt: {iter_cnt}')

                # Sampling and scoring
                setattr(self.nssampler, param_name, lower_bound)
                score_list = pool.starmap_async(_rescore, [(self.nssampler, self.graph, self.start_node) for _ in np.arange(n_trials)]).get()
                lower_bound_score = np.mean(a=score_list, axis=None)

                setattr(self.nssampler, param_name, upper_bound)
                result = pool.starmap_async(_rescore, [(self.nssampler, self.graph, self.start_node) for _ in np.arange(n_trials)]).get()
                upper_bound_score = np.mean(a=score_list, axis=None)

                setattr(self.nssampler, param_name, mid)
                score_list = pool.starmap_async(_rescore, [(self.nssampler, self.graph, self.start_node) for _ in np.arange(n_trials)]).get()
                mid_score = np.mean(a=score_list, axis=None)

                bounds, bound_scores = [lower_bound, mid, upper_bound], [lower_bound_score, mid_score, upper_bound_score]
                largest_score_indexes = np.argsort(a=bound_scores, axis=None)[::-1]  # Descending order - leargest to smallest score
                curr_score = bound_scores[largest_score_indexes[0]]  # Current largest score of the three

                # Evaluate for no improvements
                if curr_score > high_score:
                    high_score = curr_score
                    best_param_value = np.asarray(a=bounds)[largest_score_indexes[0]]
                    no_improve_cnt = 0
                else:
                    no_improve_cnt += 1
                if n_no_improve is not None and no_improve_cnt >= n_no_improve:
                    # if __debug__:
                    print(f'n_no_improve ({n_no_improve}) line crossed')
                    print(f'best_param_value: {best_param_value}')
                    return best_param_value

                # if __debug__:
                print(f'bounds: {bounds}')
                print(f'bound_scores: {bound_scores}')
                print(f'largest_score_indexes: {largest_score_indexes}')
                print(f'curr_score: {curr_score}')

                upper_bound, lower_bound = np.asarray(a=bounds)[largest_score_indexes[:2]]
                mid = (lower_bound + upper_bound) / 2.0
                if int_only:
                    mid = int(mid)
                iter_cnt += 1

        # Specific iterable of testable values given
        else:
            for value in param_values:
                setattr(self.nssampler, param_name, value)
                score_list = pool.starmap_async(_rescore, [(self.nssampler, self.graph, self.start_node) for _ in np.arange(n_trials)]).get()
                curr_score = np.mean(a=score_list, axis=None)

                if curr_score > high_score:
                    high_score = curr_score
                    best_param_value = value

                # if __debug__:
                print(f'value: {value}')
                print(f'curr_score: {curr_score}')

        # if __debug__:
        print(f'best_param_value: {best_param_value}')

        return best_param_value

    # def tune_multiple(self, params: Dict[str, Union[Iterable[float], Tuple[float, float]]], int_only: Iterable[bool]=None, n_iter=10, n_no_improve: int=None):
    #     """
    #     Optimize the current sampler for a specific network to sample, given a dictionary

    #     Args:
    #         params (Dict[str, Union[Iterable[float], Tuple[float, float]]]): Dictionary of parameter names and either a list of discretevalues or
    #                 a bounded interval (2-element tuple) for the bisection method.
    #         int_only (Iterable[bool], optional): Whether only integer values are accepted for the parameter. Defaults to None.
    #         n_iter (int, optional): Number of iterations to use before stopping. Defaults to 10.
    #         n_no_improve (int, optional): Number of iterations without improvement on best score to confor stopping. Defaults to None.

    #     Raises:
    #         ValueError: One or more specified parameter names do not exist in sampler

    #     Returns:
    #         Dict[str, Union[int, float]]: Dictionary with the same keys as 'params', but each value is the parameter value for a specific
    #             parameter with the highest achieved score during tuning.
    #     """
    #     itertools.product(*params.values())
    #     pll = Parallel(n_jobs=mp.cpu_count(), backend='multiprocessing')
    #     tuned_values = pll()(delayed(self.tune_single)(
    #     for param_name, param_value, int_only_value, n_iter, n_no_improve)
    #     retval = dict(zip(params.keys(), tuned_values))

    #     # if __debug__:
    #     print(f'retval: {retval}')
    #     return retval

#endregion

#region
class NetworkSamplerGrid:
    """Compare and contrast different metrics of resulting samples from networks among different sampling algorithms."""
    # METHODS
    def __init__(self, graph_group: Iterable[nx.Graph], sampler_group: Iterable[Any], scorer_group: Iterable[NSMethod], sampler_names: Iterable[str]=None, scorer_names: Iterable[str]=None):
        """Initializes the group of sampling algorithms to compare using one or more scoring metrics.

        Args:
            graph_group (Iterable[nx.Graph]): One or more networks to sample and evaluate. Each graph having a 'name' attribute is recommended for later labeling in tables; if absent, label for a graph will be its 
                                                0-based index in graph_group.
            sampler_group (Iterable[Any]): One or more sampling algorithms to apply, either in the form of litleballoffur instances or a custom instance from NEtworkSamplerFunctions.py 
            scorer_group (Iterable[NSMethod]): One or more scoring metrics to apply to the resulting sampled network using each given sampling algorithm. Each value in 'params' is a fixed constant.
            sampler_group (Iterable[str]): Collection of string names for each sampler in sampler_group to be used as row labels (indexes); str() value of scroer will be used instead if None. Defaults to None.
            scorer_names (Iterable[str]): Collection of string names for each scorer in scorer_group to be used as column labels; str() value of scroer will be used instead if None. Defaults to None.

        Raises:
            ValueError: The number of names designated for scorers does not equal the number of scorers in scorer_group

        Returns:
            None:
        """
        # pdb.set_trace(header='NetworkSamplerGrid - __init__ - Entering initializer')

        if len(sampler_names) != len(sampler_group):
            raise ValueError('The number of names designated for samplers does not equal the number of samplers in scorer_group.')
        elif len(scorer_names) != len(scorer_group):
            raise ValueError('The number of names designated for scorers does not equal the number of scorers in scorer_group.')

        self.graph_group = graph_group
        self.sampler_group = sampler_group
        self.sampler_names = sampler_names
        self.scorer_group = scorer_group
        self.scorer_names = scorer_names

        if __debug__:
            print(f'Number of graphs: {len(self.graph_group)}')
            print(f'Number of samplers: {len(self.sampler_group)}')
            print(f'Number of scorers: {len(self.scorer_group)}')

    def sample_by_graph(self, graph: nx.Graph, start_node: int=None, n_trials: int=1, aggregate: Callable=np.mean, dir_path: str = None, n_jobs: int = mp.cpu_count()):
        """
        Samples a specific network, possibly over many trials and aggregating the score.

        Args:
            graph: Graph to sample
            start_node (int, optional): Node where sampling starts to spread. Defaults to None.
            n_trials (int, optional): The number of times to run the each sampling algorithm when evalutating with the same scoring metric. The end score is a single value from aggregating the scores from all the 
                                        trials. Defaults to 1.
            aggregate (Callable, optional): Aggregation function over n_trials itrals for a specific scoring metric. Must take in an iterable as first parameter. Defaults to np.mean.
            dir_path (str, optional): Path for directory holdin the pickled results of NetworkSamplerGrid. The extension at the end must be '.pkl'. If None, nothing will be stored in memory. Defaults to None.
            n_jobs (int, optional): Number of jobs to divide sampling across all graphs with multiprocessing. Defaults to 1.

        Returns:
            pd.DataFrame: Dataframe with sampling algorithm as rows and scores / other data generated by specified metrics as columns, and 
        """

        # pdb.set_trace(header='NetworkSamplerGrid - samply_by_graph - Entering function')
        pool = mp.Pool(processes=16)
        graph_name = graph['name'] if 'name' in graph else str(graph)
        sample_result = None
        row_labels = [str(sampler) for sampler in self.sampler_group] if self.sampler_names is None else self.sampler_names # indexes for dataframe df
        col_labels = [str(scorer) for scorer in self.scorer_group] if self.scorer_names is None else self.scorer_names
        score_dict = dict()
        for col_name in self.scorer_names:
            score_dict.update({col_name:list()})

        if __debug__:
            print(f'row_labels: {row_labels}')
            print(f'col_labels: {col_labels}')
            print(f'initial score_dict:\n{score_dict}')

        # pdb.set_trace(header='NetworkSamplerGrid - sample_by_graph - Sampling chose graph with each provided sampling algorithm')
        for row_label, sampler in zip(row_labels, self.sampler_group):
            if __debug__:
                print(f'sampler: {row_label}')

            # Initializing sampler and sampling
            ns = NetworkSampler(sampler=sampler, scorer=None)
            sample_result = ns.sample(graph=graph, start_node=start_node)

            # Drawing and saving sample
            nx.draw(G=sample_result, pos=nx.spring_layout(G=sample_result))
            plt.show(block=False)
            plt.savefig(f'./Graph Plots/{graph_name}_{row_label}.jpg', format='JPG')

            for col_label, scorer in zip(col_labels, self.scorer_group):
                # Computing score / distribution
                ns.set_scorer(new_scorer=scorer)
                score_list = list()  # temporary use to hold scores across trials for the same  (sampler, scorer) pair

                try:
                    result = pool.starmap_async(_rescore, [(ns, graph, start_node) for _ in np.arange(n_trials)])
                    score_list = result.get()
                except:
                    for _ in np.arange(n_trials):
                        ns.sample(graph=graph, start_node=start_node)
                        score_list.append(ns.score())

                # if __debug__:
                print(f'scorer: {col_label}')
                print(f'score_list:\n{score_list}')

                # Score is a number
                if type(score_list[0]) in [int, float, np.int_, np.float_]:
                    score_dict[col_label].append(aggregate(score_list))

                # Score is an iterable
                else:
                    iter_score = score_list[0]
                    for idx in np.arange(1, n_trials):
                        iter_score += score_list[idx]

                    if __debug__:
                        print(f'iter_score:\n{iter_score}')

                    score_dict[col_label].append(iter_score)

        if __debug__:
            print(f'final score_dict:\n{score_dict}')

        df = pd.DataFrame(data=score_dict, index=row_labels)
        return df


    def sample_all_graphs(self, start_node: int=None, n_trials: Iterable[int]=None, score_finalizer: str = 'mean', dir_path: str = None, n_jobs: int = 1):
        """
        Samples each given network during initialization and creates a dataframe with sampling algorithm as row and scoring metric as column. The collection of such dataframes
        are stored into a dict, keyed by network name if it exists or the index of the network during class initialization.

        Args:
            start_node (int, optional): Node where sampling starts to spread. Defaults to None.
            n_trials (Iterable[int], optional): [description]. Defaults to None.
            score_finalizer (str, optional): [description]. Defaults to 'mean'.
            dir_path (str, optional): [description]. Defaults to None.
            n_jobs (int, optional): [description]. Defaults to 1.

        Returns:
            dict[pd.DataFrame]: Dictionary of dataframes, each being a scoreboard across all given sampling algorithms measured with all given scoring metrics for each network
        """
        # pdb.set_trace(header='NetworkSamplerGrid - sample_all_graphs - Entering')
        retval = dict()
        for index, graph in enumerate(self.graph_group):
            retval[graph['name'] if 'name' in graph else str(index)] = sample_by_graph(graph=graph, n_trials=n_trials[index], score_finalizer=score_finalizer, n_jobs=n_jobs)
        return retval

#endregion
