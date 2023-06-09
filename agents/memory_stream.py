import uuid
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from .embedding import get_embedding
import numpy as np
from datetime import datetime, timezone
from .memory import Reflection
from tabulate import tabulate
from annoy import AnnoyIndex
from .agent_api_communication import APICommunication
from tasks.task_manager import AgileTaskManager, TeamTaskManager, OrganizationTaskManager
from .memory import Plan

class MemoryStream:
    def __init__(self, retrieval_limit=5, api_communication=None):
        self.api_communication = api_communication or APICommunication("http://localhost:3008")
        self.id = str(uuid.uuid4())  # Assign a unique ID to the MemoryStream instance
        self.nodes = []
        self.retrieval_limit = retrieval_limit
        self.ann_index = AnnoyIndex(1536, 'angular')  # Assuming  embeddings have 1536 dimensions
        self.individual_task_manager = AgileTaskManager()
        self.team_task_manager = TeamTaskManager()
        self.organization_task_manager = OrganizationTaskManager()

    def add_memory(self, memory_data):
        self.nodes.append(memory_data)
        self.ann_index.add_item(len(self.nodes) - 1, memory_data.embedding)  # Add the memory's embedding to the ANN index
        if isinstance(memory_data, Plan):
            plan_level = memory_data.level
            if plan_level is not None:
                if plan_level == 'individual':
                    self.individual_task_manager.add_task(memory_data)
                elif plan_level == 'team':
                    self.team_task_manager.add_task(memory_data)
                elif plan_level == 'organization':
                    self.organization_task_manager.add_task(memory_data)
                else:
                    raise ValueError("Invalid plan level specified")

    # When we add a plan memory, we can specify the level as an argument:
    # memory_stream.add_memory(plan_memory, plan_level='individual')


    def get_memory_by_id(self, memory_id):
        for memory in self.nodes:
            if memory.id == memory_id:
                return memory
        return None

    def delete_memory(self, memory_id):
        self.nodes = [node for node in self.nodes if node["id"] != memory_id]

    def search_memory_group(self, query, current_time, group_memory_stream):
        pass    

    def decay_function(self, time_elapsed):
        decay_rate = 0.0001
        return np.exp(-time_elapsed * decay_rate)

    def calculate_relevance(self, memory, query_memory):
        memory_vector = memory["embedding"]
        query_memory_vector = query_memory["embedding"]
        return cosine_similarity(memory_vector, query_memory_vector)

    def calculate_importance(self, memory):
        return memory["importance"]

    def calculate_recency(self, memory, current_time):
        memory_time = memory.timestamp
        time_elapsed = current_time - memory_time
        return self.decay_function(time_elapsed.total_seconds())
    
    def min_max_scale(self, value, min_value, max_value):
        if max_value == min_value:
            return 0
        return (value - min_value) / (max_value - min_value)
    
    def _is_memory_relevant_to_task(self, memory, task):
        return str(task.number) in memory.content



    def retrieve_memory(self, query, current_time):
        query_embedding = get_embedding(query)

        # Build the ANN index
        # self.ann_index.build(10)  # 10 trees for ANN index, can be tuned
        
        # Get the indices of the top k most similar memories
        top_k_indices = self.ann_index.get_nns_by_vector(query_embedding, self.retrieval_limit)

        # Get the top k most similar memories using their indices
        top_k_memories = [self.nodes[i] for i in top_k_indices]

        scored_memories = []
        for memory in top_k_memories:
            query_embedding_array = np.array(query_embedding).reshape(1, -1)
            memory_embedding_array = np.array(memory.embedding).reshape(1, -1)
            relevance = cosine_similarity(query_embedding_array, memory_embedding_array)[0][0]
            recency = self.calculate_recency(memory, current_time)
            importance = memory.importance

            scored_memories.append((memory, recency, relevance, importance))

        min_recency, max_recency = min(s[1] for s in scored_memories), max(s[1] for s in scored_memories)
        min_relevance, max_relevance = min(s[2] for s in scored_memories), max(s[2] for s in scored_memories)
        min_importance, max_importance = min(s[3] for s in scored_memories), max(s[3] for s in scored_memories)

        memory_scores = []
        headers = ["Memory ID", "Count", "Time Elapsed", "Recency", "Normalized Recency", "Normalized Relevance", "Normalized Importance", "Total Value"]
        data = []

        for memory, recency, relevance, importance in scored_memories:
            norm_recency = self.min_max_scale(recency, min_recency, max_recency)
            norm_relevance = self.min_max_scale(relevance, min_relevance, max_relevance)
            norm_importance = self.min_max_scale(importance, min_importance, max_importance)

            memory_time = memory.timestamp
            time_elapsed = current_time - memory_time
            time_elapsed_str = f"{time_elapsed.seconds // 3600:02d}:{(time_elapsed.seconds // 60) % 60:02d}:{time_elapsed.seconds % 60:02d}"

            final_score = norm_recency + norm_relevance + norm_importance

            row = [memory.id, memory.number, time_elapsed_str, recency, norm_recency, norm_relevance, norm_importance, final_score]
            data.append(row)

            if isinstance(memory, Reflection):
                print(f"Evidence: {', '.join(memory.evidence)}")

            if final_score > 0:
                memory_scores.append((memory, final_score))

        # Print the table only once
        table = tabulate(data, headers=headers, tablefmt="grid")
        print(table)

        # Sort the memories by their scores and retrieve the top ones
        retrieved_memories = [memory for memory, score in sorted(memory_scores, key=lambda x: x[1], reverse=True)[:self.retrieval_limit]]

        # Update the last_viewed attribute for the retrieved memories
        for memory in retrieved_memories:
            memory.update_last_viewed(current_time)
            
            # Get tasks from individual, team, and organization levels
        all_tasks = (
            self.individual_task_manager.get_tasks()
            + self.team_task_manager.get_tasks()
            + self.organization_task_manager.get_tasks()
        )

        # Filter the top_k_memories based on their relevance to the tasks
        relevant_memories = []
        for memory in top_k_memories:
            for task in all_tasks:
                if self._is_memory_relevant_to_task(memory, task):
                    relevant_memories.append(memory)
                    break

        return retrieved_memories
